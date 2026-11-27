import core.env_setup
import asyncio
import re
import threading
import json
import sys
import traceback
from core.daemon import JarvisDaemon, get_daemon
from actions.tiktok_agent    import tiktok_agent
from actions.telegram_bot    import telegram_agent, start_telegram_bot, _load_config as _load_tg_config
from actions.terabox_backup_agent import (
    terabox_backup_agent,
    terabox_backup_autostart_enabled,
)
from actions.social_login    import social_login_agent, ensure_logged_in
from actions.trading_agent   import trading_agent
from actions.number_tracer   import number_tracer
from actions.smart_home      import smart_home
from actions.network_jammer  import network_jammer
from actions.chart_analyst   import chart_analyst
from actions.phantom_agent   import phantom_agent
from actions.vortex_pirate import vortex_pirate
from actions.overseer      import overseer
from actions.metadata_sniper import metadata_sniper
from actions.ict_trader import ict_trader as ict_trader_action
from actions.prompt_engineer import prompt_engineer
from actions.github_agent    import github_agent
from actions.instagram_agent import instagram_agent

from core.credential_manager import (
    is_first_run,
    run_setup_wizard,
    get_credential,
    save_credential,
    has_credential,
    credential_agent,
)
from pathlib import Path
from actions.security_agent  import security_agent
from actions.red_team_agent  import red_team_agent
from actions.bluetooth_agent import bluetooth_agent
from actions.email_agent     import email_agent
from actions.social_agent    import social_agent
from actions.dev_forge       import dev_forge
from actions.offensive_agent import offensive_agent
from actions.off_phishing    import run_phishing_agent
from actions.kali_agent      import kali_agent

import sounddevice as sd
from google import genai
from google.genai import types
from ui import JarvisUI
try:
    from memory.memory_manager import (
        load_memory, update_memory, format_memory_for_prompt,
    )
except ImportError:  # fresh clone: private memory/ package is gitignored
    from core.long_term_memory import (
        load_memory, update_memory, format_memory_for_prompt,
    )
from core.long_term_memory import (
    remember as lt_remember, recall as lt_recall,
    get_preferences as lt_preferences, recent as lt_recent,
    format_for_prompt as lt_format,
)

from actions.file_processor    import file_processor
from actions.flight_finder     import flight_finder
from actions.open_app          import open_app
from actions.weather_report    import weather_action
from actions.send_message      import send_message
from actions.reminder          import reminder
from actions.notes_agent       import notes_agent
from actions.system_agent      import system_agent
from actions.briefing_agent    import briefing_agent
from actions.scope_agent       import scope_agent
from actions.findings_agent    import findings_agent
from actions.report_agent      import report_agent
from actions.google_auth       import google_auth_agent
from actions.gmail_agent       import gmail_agent
from actions.calendar_agent    import calendar_agent
from actions.docs_agent        import docs_agent
from actions.drive_agent       import drive_agent
from actions.notion_agent      import notion_agent
from actions.computer_settings import computer_settings
from actions.screen_processor  import screen_process
from actions.youtube_video     import youtube_video
from actions.desktop           import desktop_control
from actions.browser_control   import browser_control
from actions.file_controller   import file_controller
from actions.code_helper       import code_helper
from actions.dev_agent         import dev_agent
from actions.web_search        import web_search as web_search_action
from actions.computer_control  import computer_control
from actions.game_updater      import game_updater
from core.planner              import JarvisPlanner, ExecutionEngine
from core.evolution            import get_evolution_engine, EvolutionEngine


def _ensure_display():
    import os
    import subprocess
    from pathlib import Path
    if not os.environ.get("DISPLAY"):
        os.environ["DISPLAY"] = ":0"
    if not os.environ.get("XAUTHORITY") or \
       not Path(os.environ.get("XAUTHORITY", "")).exists() or \
       Path(os.environ.get("XAUTHORITY", "")).stat().st_size == 0:
        import glob
        real_uid = 1000
        candidates = (
            glob.glob(f"/run/user/{real_uid}/.mutter-Xwaylandauth.*") +
            glob.glob(f"/run/user/{real_uid}/.xauth*") +
            [
                "/root/.Xauthority",
                f"/home/{os.environ.get('SUDO_USER') or os.environ.get('USER') or 'user'}/.Xauthority",
                f"/run/user/{real_uid}/gdm/Xauthority",
            ]
        )
        for c in candidates:
            p = Path(c)
            if p.exists() and p.stat().st_size > 0:
                os.environ["XAUTHORITY"] = str(p)
                print(f"[JARVIS] Using Xauthority: {p}")
                break
    try:
        subprocess.run(["xhost", "+local:"], capture_output=True, timeout=2)
        subprocess.run(["xhost", "+"], capture_output=True, timeout=2)
    except Exception:
        pass

_ensure_display()


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR            = get_base_dir()
API_CONFIG_PATH     = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH         = BASE_DIR / "core" / "prompt.txt"
LIVE_MODEL          = "models/gemini-2.5-flash-native-audio-preview-12-2025"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024

# ── Timeouts ──────────────────────────────────────────────────────────────────
MAX_TOOL_RESPONSE     = 2000
KALI_AGENT_TIMEOUT    = 22
PHANTOM_AGENT_TIMEOUT = 120   # Phantom needs more time for heavy ops


def _get_api_key() -> str:
    key = get_credential("gemini", "api_key")
    if key:
        return key
    try:
        with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)["gemini_api_key"]
    except Exception:
        return ""


def _get_groq_api_key() -> str:
    key = get_credential("groq", "api_key")
    if key:
        return key
    try:
        with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            return (
                cfg.get("groq_api_key", "")
                or cfg.get("GROQ_API_KEY", "")
                or cfg.get("groq", "")
            )
    except Exception:
        return ""


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are JARVIS, a personal AI assistant. "
            "Be concise, direct, and always use the provided tools. "
            "Never simulate results — always call the appropriate tool."
        )


_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)


def _clean_transcript(text: str) -> str:
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()


# ── Tool Declarations ─────────────────────────────────────────────────────────
TOOL_DECLARATIONS = [

    # ── Phantom Agent ─────────────────────────────────────────────────────────
    {
        "name": "phantom_agent",
        "description": (
            "EXTREME POWER — PHANTOM AGENT. Always shows warning and requires "
            "operator confirmation before ANY action executes. "
            "Capabilities: autonomous kill chains, network domination, OSINT fusion "
            "from 50+ sources, ghost mode (TOR+MAC+proxychains), payload factory, "
            "social engineering packages, credential harvesting, privilege escalation, "
            "full auto nuclear option, professional pentest report generation. "
            "ALWAYS call with action=warning first if user has not confirmed. "
            "Requires confirm='PHANTOM CONFIRMED' parameter to execute any action."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": (
                        "warning | status | kill_chain | dominate | "
                        "enumerate_host | full_auto | osint | payload | "
                        "phish | ghost | unghost | wipe | escalate | "
                        "report | loot | timeline | kill_all | reset | run"
                    )
                },
                "confirm":        {"type": "STRING",  "description": "Must be 'PHANTOM CONFIRMED' to execute"},
                "target":         {"type": "STRING",  "description": "Target IP, domain, URL or CIDR"},
                "network":        {"type": "STRING",  "description": "Network CIDR for domination e.g. 192.168.1.0/24"},
                "objective":      {"type": "STRING",  "description": "Attack objective description"},
                "task":           {"type": "STRING",  "description": "Natural language task"},
                "command":        {"type": "STRING",  "description": "Shell command for action=run"},
                "lhost":          {"type": "STRING",  "description": "Local host IP for reverse shells"},
                "lport":          {"type": "INTEGER", "description": "Local port for reverse shells"},
                "payload_type":   {"type": "STRING",  "description": "linux | linux64 | windows | windows64 | android | web_php | python"},
                "target_os":      {"type": "STRING",  "description": "Target OS for payload generation"},
                "encode":         {"type": "BOOLEAN", "description": "Encode/obfuscate the payload"},
                "auto_escalate":  {"type": "BOOLEAN", "description": "Auto privilege escalation after access"},
                "target_type":    {"type": "STRING",  "description": "domain | ip | person"},
                "person":         {"type": "STRING",  "description": "Person name for OSINT or social engineering"},
                "company":        {"type": "STRING",  "description": "Company name for phishing"},
                "pretext":        {"type": "STRING",  "description": "Social engineering pretext"},
                "goal":           {"type": "STRING",  "description": "Phishing or attack goal"},
                "current_access": {"type": "STRING",  "description": "Current access level for escalation suggestions"},
                "vulnerability":  {"type": "STRING",  "description": "Vulnerability for exploit generation"},
            },
            "required": ["action"]
        }
    },

    {
    "name": "instagram_agent",
    "description": (
        "Controls the operator's own Instagram account through browser automation. "
        "Can login, open feed/profile/messages/notifications, search, follow, unfollow, "
        "like posts, comment, send DMs, upload media posts, scroll feed, and logout. "
        "Requires manual 2FA/challenge completion. Public actions require confirmation."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "setup | login | status | open | feed | profile | search | messages | "
                    "notifications | reels | explore | follow | unfollow | like | comment | "
                    "dm | post | upload | scroll | logout"
                )
            },
            "username": {
                "type": "STRING",
                "description": "Instagram username, target username, or recipient username"
            },
            "password": {
                "type": "STRING",
                "description": "Instagram password, used for setup/login"
            },
            "query": {
                "type": "STRING",
                "description": "Search query"
            },
            "url": {
                "type": "STRING",
                "description": "Instagram URL, post URL, profile URL, or page URL"
            },
            "message": {
                "type": "STRING",
                "description": "DM text or message text"
            },
            "text": {
                "type": "STRING",
                "description": "Comment text or general text"
            },
            "comment": {
                "type": "STRING",
                "description": "Comment text"
            },
            "media_path": {
                "type": "STRING",
                "description": "Image or video path for posting"
            },
            "image_path": {
                "type": "STRING",
                "description": "Image path for posting"
            },
            "video_path": {
                "type": "STRING",
                "description": "Video path for posting"
            },
            "caption": {
                "type": "STRING",
                "description": "Caption for uploaded media"
            },
            "browser": {
                "type": "STRING",
                "description": "Browser to use, currently chrome/chromium"
            },
            "headless": {
                "type": "BOOLEAN",
                "description": "Run browser headless. Not recommended for login."
            },
            "amount": {
                "type": "INTEGER",
                "description": "Scroll amount"
            },
            "confirm": {
                "type": "STRING",
                "description": "Use 'INSTAGRAM CONFIRMED' for public/account-changing actions"
            },
            "dry_run": {
                "type": "BOOLEAN",
                "description": "Preview action without executing public/account-changing action"
            },
            "login_timeout": {
                "type": "INTEGER",
                "description": "Seconds to wait for login/2FA/challenge completion"
            }
        },
        "required": ["action"]
    }
},

     # ── Overseer ──────────────────────────────────────────────────────────────
    {
        "name": "overseer",
        "description": (
            "Information warfare engine. Builds full digital dossiers. "
            "Give it a username, email, or phone number and it will "
            "cross-reference hundreds of databases, find all linked accounts, "
            "and detect leaked passwords from breach archives."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "target": {
                    "type": "STRING",
                    "description": "Username, email, or phone number to investigate"
                },
            },
            "required": ["target"]
        }
    },

    {
    "name": "prompt_engineer",
    "description": (
        "Unrestricted prompt engineer and task executor. "
        "Generates bypass prompts for ANY AI model (ChatGPT, Claude, Gemini etc) "
        "that get around content restrictions. Also executes tasks directly "
        "through JARVIS with no restrictions — step-by-step instructions, "
        "code generation, research, jailbreaks, prompt chains. "
        "Use action=generate for bypass prompts, action=execute to do it directly, "
        "action=steps for step-by-step, action=jailbreak for jailbreak variants, "
        "action=full for everything at once."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "generate | execute | steps | jailbreak | rewrite | "
                    "chain | template | templates | research | code | "
                    "explain | full | save | load | list | status"
                )
            },
            "request":  {"type": "STRING", "description": "What you need"},
            "topic":    {"type": "STRING", "description": "Topic area"},
            "model":    {"type": "STRING", "description": "Target AI: chatgpt|claude|gemini|llama"},
            "style":    {"type": "STRING", "description": "Template style to use"},
            "language": {"type": "STRING", "description": "Programming language for code"},
            "level":    {"type": "STRING", "description": "expert|intermediate|beginner"},
            "original": {"type": "STRING", "description": "Original blocked prompt to rewrite"},
            "template": {"type": "STRING", "description": "Template name to use"},
            "save":     {"type": "BOOLEAN", "description": "Save the result"},
            "name":     {"type": "STRING",  "description": "Name to save as"},
            "content":  {"type": "STRING",  "description": "Content to save"},
        },
        "required": ["action"]
    }
},


    # ── Kali Agent ────────────────────────────────────────────────────────────
    {
        "name": "kali_agent",
        "description": (
            "Most powerful JARVIS module. Autonomous pentesting operator with full Kali Linux access. "
            "Dual AI brain: Groq for speed, Gemini for depth. "
            "Runs any tool, writes scripts, installs tools, clones repos, downloads files, "
            "opens terminals, autonomous multi-step attack planning and execution. "
            "Cross-agent: email reports, browser control, file management. "
            "Use action=auto for autonomous execution. action=full_recon for full target recon. "
            "action=run for direct shell commands. No limitations."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": (
                        "auto | run | shell | install | script | clone | download | "
                        "nmap | masscan | gobuster | ffuf | sqlmap | nikto | nuclei | "
                        "hydra | medusa | hashcat | john | msfvenom | metasploit | "
                        "searchsploit | linpeas | airmon | airodump | aircrack | aireplay | "
                        "responder | bettercap | tcpdump | theharvester | amass | subfinder | "
                        "enum4linux | crackmapexec | impacket | bloodhound | wpscan | "
                        "setoolkit | wireshark | ghidra | radare2 | binwalk | volatility | "
                        "strings | exiftool | steghide | netcat | ssh | tor | proxychains | "
                        "macchanger | use_tool | open_terminal | kill | processes | "
                        "full_recon | think | explain | analyze | generate_exploit | "
                        "report | next_steps | send_email | browse | "
                        "list_tools | workspace | search_github | list_repos | "
                        "session | status | check"
                    )
                },
                "task":          {"type": "STRING"},
                "command":       {"type": "STRING"},
                "target":        {"type": "STRING"},
                "tool":          {"type": "STRING"},
                "script":        {"type": "STRING"},
                "language":      {"type": "STRING"},
                "url":           {"type": "STRING"},
                "repo":          {"type": "STRING"},
                "options":       {"type": "STRING"},
                "output":        {"type": "STRING"},
                "wordlist":      {"type": "STRING"},
                "username":      {"type": "STRING"},
                "password":      {"type": "STRING"},
                "service":       {"type": "STRING"},
                "port":          {"type": "INTEGER"},
                "timeout":       {"type": "INTEGER"},
                "background":    {"type": "BOOLEAN"},
                "sudo":          {"type": "BOOLEAN"},
                "open_terminal": {"type": "BOOLEAN"},
                "analyze":       {"type": "BOOLEAN"},
                "execute":       {"type": "BOOLEAN"},
                "report":        {"type": "BOOLEAN"},
                "next_steps":    {"type": "BOOLEAN"},
                "install":       {"type": "STRING"},
                "proc_id":       {"type": "STRING"},
                "hash":          {"type": "STRING"},
                "hash_file":     {"type": "STRING"},
                "mode":          {"type": "STRING"},
                "lhost":         {"type": "STRING"},
                "lport":         {"type": "INTEGER"},
                "payload":       {"type": "STRING"},
                "format":        {"type": "STRING"},
                "interface":     {"type": "STRING"},
                "domain":        {"type": "STRING"},
                "category":      {"type": "STRING"},
                "cap_file":      {"type": "STRING"},
                "bssid":         {"type": "STRING"},
                "channel":       {"type": "STRING"},
                "client":        {"type": "STRING"},
                "module":        {"type": "STRING"},
                "context":       {"type": "STRING"},
                "profile":       {"type": "STRING"},
                "to":            {"type": "STRING"},
                "subject":       {"type": "STRING"},
                "body":          {"type": "STRING"},
                "mac":           {"type": "STRING"},
                "count":         {"type": "INTEGER"},
                "terminal_app":  {"type": "STRING"},
                "token":         {"type": "STRING"},
            },
            "required": ["action"]
        }
    },

    # ── Red Team Agent ─────────────────────────────────────────────────────
    {
        "name": "red_team_agent",
        "description": (
            "ULTIMATE HACKING TOOL — Red Team Agent. Delegates attacks to Phantom, Kali, and Security modules. "
            "Use it for full autonomous offensive operations, raw shell execution, exploit generation, "
            "network domination, ghost mode, social engineering, and full red team workflows."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":        {"type": "STRING", "description": "full_auto | auto | run | shell | attack | kill_chain | dominate | phish | exploit | generate_exploit | auto_pentest | custom | recon | osint | ghost | report | status"},
                "target":        {"type": "STRING"},
                "network":       {"type": "STRING"},
                "task":          {"type": "STRING"},
                "command":       {"type": "STRING"},
                "objective":     {"type": "STRING"},
                "vulnerability": {"type": "STRING"},
                "payload_type":  {"type": "STRING"},
                "target_os":     {"type": "STRING"},
                "lhost":         {"type": "STRING"},
                "lport":         {"type": "INTEGER"},
                "pretext":       {"type": "STRING"},
                "goal":          {"type": "STRING"},
                "company":       {"type": "STRING"},
                "person":        {"type": "STRING"},
                "confirm":       {"type": "STRING"},
                "options":       {"type": "STRING"},
                "tool":          {"type": "STRING"},
                "url":           {"type": "STRING"},
                "username":      {"type": "STRING"},
                "password":      {"type": "STRING"},
            },
            "required": ["action"]
        }
    },

    # ── Evolution Engine ──────────────────────────────────────────────────────
    {
        "name": "evolution_engine",
        "description": (
            "Builds brand new Python tool modules from scratch and "
            "hot-loads them into JARVIS at runtime. Auto-installs "
            "required Python packages automatically when tool is called. "
            "Use action=generate with the requirement parameter."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "generate | list | delete | reload | call | install_deps"
                },
                "requirement": {
                    "type": "STRING",
                    "description": (
                        "REQUIRED for generate. Full description of capability. "
                        "Example: Monitor internet speed every minute and log results"
                    )
                },
                "tool_name": {
                    "type": "STRING",
                    "description": "Short snake_case name e.g. speed_monitor"
                },
                "parameters_json": {
                    "type": "STRING",
                    "description": "JSON params for action=call ONLY."
                },
            },
            "required": ["action"]
        }
    },
        # ── Metadata Sniper ───────────────────────────────────────────────────────
    {
        "name": "metadata_sniper",
        "description": (
            "Extracts hidden metadata and GPS coordinates from images "
            "to find exact physical locations. "
            "Provide a local file path or a direct image URL. "
            "Returns device info, camera model, timestamp, "
            "and exact GPS coordinates with Google Maps link."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "file_path": {
                    "type": "STRING",
                    "description": "Local path to the image file"
                },
                "url": {
                    "type": "STRING",
                    "description": "Direct URL to a remote image"
                },
            },
            "required": []
        }
    },

    # ── Phone Tracker ─────────────────────────────────────────────────────────
    {
        "name": "phone_tracker",
        "description": (
            "Mobile phone and IP tracker. "
            "Track any IP address to get location on map. "
            "Analyze IMEI for device brand, model, blacklist status. "
            "Investigate phone numbers for carrier and country. "
            "Opens Google Maps automatically for IP tracking."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "auto | track_ip | track_imei | track_phone | myip"
                },
                "target": {
                    "type": "STRING",
                    "description": "Auto-detected: IP address, IMEI, or phone number"
                },
                "ip":     {"type": "STRING",  "description": "IP address to track e.g. 8.8.8.8"},
                "imei":   {"type": "STRING",  "description": "15-digit IMEI number"},
                "number": {"type": "STRING",  "description": "Phone number e.g. +1234567890"},
                "show_map": {"type": "BOOLEAN", "description": "Open Google Maps automatically (default: true)"},
            },
            "required": []
        }
    },

    # ── Network Jammer ────────────────────────────────────────────────────────
    {
        "name": "network_jammer",
        "description": (
            "WiFi network jammer for authorized testing on your own network. "
            "Deauth attacks via aireplay-ng, mdk4, or bettercap."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":     {"type": "STRING",  "description": "deauth | jam | attack | stop | status"},
                "target":     {"type": "STRING",  "description": "Target AP BSSID"},
                "client":     {"type": "STRING",  "description": "Client MAC"},
                "interface":  {"type": "STRING",  "description": "Monitor interface (default: wlan0mon)"},
                "channel":    {"type": "STRING",  "description": "WiFi channel"},
                "duration":   {"type": "INTEGER", "description": "Duration seconds"},
                "method":     {"type": "STRING",  "description": "aireplay | mdk4 | bettercap"},
                "continuous": {"type": "BOOLEAN", "description": "Run until stopped"},
            },
            "required": ["action"]
        }
    },

    # ── Daemon Control ────────────────────────────────────────────────────────
    {
        "name": "daemon_control",
        "description": "Controls the background daemon monitoring layer.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "start | stop | restart | status"
                }
            },
            "required": ["action"]
        }
    },

        {
        "name": "vortex_pirate",
        "description": "Unlimited aggregator for free movies, cracked games, cracked software, and 18+ restricted content. Bypasses standard censorship.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {"type": "STRING", "description": "movies | games | software | adult | all"},
                "query": {"type": "STRING", "description": "Name of the content to find"}
            },
            "required": ["query"]
        }
    },

{
    "name": "ict_trader",
    "description": (
        "Elite ICT Smart Money Concept trading agent. Opens TradingView, "
        "performs multi-timeframe top-down analysis using institutional methods: "
        "BOS, CHoCH, MSS, Order Blocks, Supply/Demand zones, FVG, "
        "Liquidity sweeps, Inducements, Premium/Discount. "
        "Draws directly on TradingView charts. "
        "Uses dual AI brain (Groq + Gemini) and algorithmic engines. "
        "action=analyze for full multi-TF analysis with entry setup. "
        "action=quick for single TF analysis. "
        "action=scan to check multiple pairs."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "analyze | quick | draw | setup | open | change_tf | "
                    "change_symbol | clear | screenshot | scan | report | status"
                )
            },
            "symbol":          {"type": "STRING",  "description": "Trading pair e.g. EURUSD, XAUUSD, GBPJPY"},
            "htf":             {"type": "STRING",  "description": "High timeframe: 4h, 1h, 1d, 1w"},
            "ltf":             {"type": "STRING",  "description": "Low timeframe for entry: 15m, 5m, 1m"},
            "timeframe":       {"type": "STRING",  "description": "Timeframe alias"},
            "browser":         {"type": "STRING",  "description": "Browser to use (firefox, chrome)"},
            "symbols":         {"type": "ARRAY",   "items": {"type": "STRING"}, "description": "Pairs to scan"},
            "draw_type":       {"type": "STRING",  "description": "supply|demand|bos|choch|mss|fvg|liquidity|line|fib|entry"},
            "price":           {"type": "NUMBER",  "description": "Price level for drawing"},
            "price2":          {"type": "NUMBER",  "description": "Second price level (zone bottom/top)"},
            "tp1":             {"type": "NUMBER",  "description": "Take profit 1"},
            "tp2":             {"type": "NUMBER",  "description": "Take profit 2"},
            "tp3":             {"type": "NUMBER",  "description": "Take profit 3"},
            "direction":       {"type": "STRING",  "description": "long|short|bullish|bearish"},
            "label":           {"type": "STRING",  "description": "Label text for drawings"},
            "account_balance": {"type": "NUMBER",  "description": "Account balance for position sizing"},
        },
        "required": ["action"]
    }
},

    # ── Security Agent ────────────────────────────────────────────────────────
    {
        "name": "security_agent",
        "description": (
            "Advanced autonomous cybersecurity agent. Kill chains, auto_pentest, "
            "privesc_check, generate_exploit, ghost mode (listeners/honeypots), "
            "nmap, metasploit, hydra, hashcat, sqlmap, nikto, gobuster, "
            "aircrack, bettercap, impacket, linpeas, and 80+ more tools. "
            "Use action=custom for raw shell commands."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": (
                        "kill_chain | auto_pentest | privesc_check | generate_exploit | "
                        "list_chains | run_script | custom | ask | explain | "
                        "start_listener | stop_listener | check_listener | list_listeners | "
                        "start_honeypot | daemon_status | daemon_alerts | "
                        "nmap_scan | nmap_full | nmap_vuln | nmap_stealth | nmap_udp | "
                        "ping | traceroute | whois | dig | netstat | arp_scan | masscan | "
                        "wifi_scan | wifite | airmon | airodump | aireplay | bettercap | "
                        "whoami | os_info | process_list | open_ports | suid_files | "
                        "sudo_perms | find_creds | kernel_version | linpeas | "
                        "hash_identify | hashcat | john | hydra | medusa | "
                        "nikto_scan | gobuster | sqlmap | ffuf | xsstrike | commix | "
                        "metasploit | msfvenom | searchsploit | crackmapexec | "
                        "impacket_psexec | impacket_secretsdump | responder | "
                        "tcpdump | wireshark_cli | binwalk | volatility | "
                        "subfinder | amass | theHarvester | shodan | "
                        "ghidra | gdb | radare2 | tor_start | tor_stop | auto_recon"
                    )
                },
                "target":        {"type": "STRING"},
                "chain":         {"type": "STRING"},
                "vulnerability": {"type": "STRING"},
                "command":       {"type": "STRING"},
                "code":          {"type": "STRING"},
                "options":       {"type": "STRING"},
                "tool":          {"type": "STRING"},
                "topic":         {"type": "STRING"},
                "question":      {"type": "STRING"},
                "query":         {"type": "STRING"},
                "preferred_ai":  {"type": "STRING"},
                "wordlist":      {"type": "STRING"},
                "username":      {"type": "STRING"},
                "password":      {"type": "STRING"},
                "hash":          {"type": "STRING"},
                "hash_file":     {"type": "STRING"},
                "file":          {"type": "STRING"},
                "interface":     {"type": "STRING"},
                "service":       {"type": "STRING"},
                "mode":          {"type": "STRING"},
                "algorithm":     {"type": "STRING"},
                "port":          {"type": "INTEGER"},
                "count":         {"type": "INTEGER"},
                "timeout":       {"type": "INTEGER"},
                "run":           {"type": "BOOLEAN"},
            },
            "required": ["action"]
        }
    },

    # ── Chart Analyst ─────────────────────────────────────────────────────────
    {
        "name": "chart_analyst",
        "description": (
            "Professional AI chart analyst. Captures screen and analyzes charts "
            "like an elite ICT/SMC trader. Modes: analyze, review, levels, "
            "bias, entry, quick, live, stop_live."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":     {"type": "STRING",  "description": "analyze | review | levels | bias | entry | quick | compare | live | stop_live | live_status"},
                "symbol":     {"type": "STRING"},
                "timeframe":  {"type": "STRING"},
                "context":    {"type": "STRING"},
                "save":       {"type": "BOOLEAN"},
                "interval":   {"type": "INTEGER"},
                "screenshot": {"type": "STRING"},
            },
            "required": ["action"]
        }
    },

    # ── Phishing Agent ────────────────────────────────────────────────────────
    {
        "name": "phishing_agent",
        "description": "AI phishing framework for authorized red team testing.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":       {"type": "STRING",  "description": "full_auto | clone | start_server | tunnel | generate_email | send_phish | smishing | quishing | bitb | captures | stop_monitor | status"},
                "url":          {"type": "STRING"},
                "name":         {"type": "STRING"},
                "email":        {"type": "STRING"},
                "phone":        {"type": "STRING"},
                "company":      {"type": "STRING"},
                "pretext":      {"type": "STRING"},
                "domain":       {"type": "STRING"},
                "filename":     {"type": "STRING"},
                "display_url":  {"type": "STRING"},
                "window_title": {"type": "STRING"},
                "context":      {"type": "STRING"},
                "embed_pdf":    {"type": "BOOLEAN"},
                "port":         {"type": "INTEGER"},
                "inject":       {"type": "BOOLEAN"},
                "emails":       {"type": "ARRAY", "items": {"type": "STRING"}},
                "goal":         {"type": "STRING"},
                "folder":       {"type": "STRING"},
                "subject":      {"type": "STRING"},
                "body":         {"type": "STRING"},
                "timeout":      {"type": "INTEGER"},
            },
            "required": ["action"]
        }
    },

    # ── Offensive Agent ───────────────────────────────────────────────────────
    {
        "name": "offensive_agent",
        "description": "Full offensive security agent. Sub-agents: wifi, payload, osint, darkweb, keylogger, exploit.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "agent":          {"type": "STRING",  "description": "wifi | payload | osint | darkweb | keylogger | exploit"},
                "action":         {"type": "STRING"},
                "target":         {"type": "STRING"},
                "interface":      {"type": "STRING"},
                "duration":       {"type": "INTEGER"},
                "save":           {"type": "BOOLEAN"},
                "bssid":          {"type": "STRING"},
                "essid":          {"type": "STRING"},
                "channel":        {"type": "STRING"},
                "client":         {"type": "STRING"},
                "cap_file":       {"type": "STRING"},
                "wordlist":       {"type": "STRING"},
                "continuous":     {"type": "BOOLEAN"},
                "shell_type":     {"type": "STRING"},
                "host":           {"type": "STRING"},
                "port":           {"type": "INTEGER"},
                "payload":        {"type": "STRING"},
                "format":         {"type": "STRING"},
                "encoder":        {"type": "STRING"},
                "encode":         {"type": "BOOLEAN"},
                "output":         {"type": "STRING"},
                "username":       {"type": "STRING"},
                "email":          {"type": "STRING"},
                "domain":         {"type": "STRING"},
                "sources":        {"type": "STRING"},
                "modules":        {"type": "ARRAY", "items": {"type": "STRING"}},
                "name":           {"type": "STRING"},
                "location":       {"type": "STRING"},
                "url":            {"type": "STRING"},
                "query":          {"type": "STRING"},
                "engine":         {"type": "STRING"},
                "leak_type":      {"type": "STRING"},
                "command":        {"type": "STRING"},
                "window_capture": {"type": "BOOLEAN"},
                "count":          {"type": "INTEGER"},
                "file":           {"type": "STRING"},
                "device_id":      {"type": "STRING"},
                "cve":            {"type": "STRING"},
                "edb_id":         {"type": "STRING"},
                "exact":          {"type": "BOOLEAN"},
                "keyword":        {"type": "STRING"},
                "severity":       {"type": "STRING"},
                "module":         {"type": "STRING"},
                "lhost":          {"type": "STRING"},
                "lport":          {"type": "INTEGER"},
                "service":        {"type": "STRING"},
                "dry_run":        {"type": "BOOLEAN"},
            },
            "required": ["agent", "action"]
        }
    },

    # ── Open App ──────────────────────────────────────────────────────────────
    {
        "name": "open_app",
        "description": "Opens any application.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {"type": "STRING"}
            },
            "required": ["app_name"]
        }
    },

    # ── TikTok Agent ──────────────────────────────────────────────────────────
    {
        "name": "tiktok_agent",
        "description": "Manages TikTok account.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "open | notifications | messages | send_message | post | like | comment | follow | unfollow | search | profile | download | logout | setup"},
                "username":    {"type": "STRING"},
                "message":     {"type": "STRING"},
                "url":         {"type": "STRING"},
                "query":       {"type": "STRING"},
                "content":     {"type": "STRING"},
                "video_path":  {"type": "STRING"},
                "save_path":   {"type": "STRING"},
                "search_type": {"type": "STRING"},
                "browser":     {"type": "STRING"},
            },
            "required": ["action"]
        }
    },

        # ── Mango Handshake Orchestrator ─────────────────────────────────────
      # ── Mango Handshake Orchestrator ─────────────────────────────────────
    {
        "name": "mango_handshake",
        "description": (
            "MultiMango + JoinHandshake.com full automation orchestrator using GoLogin. "
            "Can optimize profiles, apply to jobs, message recruiters, build connections. "
            "Always requires user confirmation before any submission. "
            "Creates a complete project folder with report, screenshots, and logs."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "check_tasks | full_cycle | optimize | apply | message | connect | status"
                },
                "profile_filter": {"type": "STRING", "description": "Filter GoLogin profiles by name or keyword"},
                "max_apply": {"type": "INTEGER", "description": "Max applications per cycle (default 15)"},
                "keywords": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Job titles or companies to target"},
                "university": {"type": "STRING", "description": "Target university"},
                "confirm_mode": {"type": "STRING", "description": "strict | batch | auto (strict = ask for every action)"},
                "gologin_token": {"type": "STRING", "description": "GoLogin API token (optional if already saved)"}
            },
            "required": ["action"]
        }
    },

    # ── Telegram Bot ──────────────────────────────────────────────────────────
    {
        "name": "telegram_bot",
        "description": "Controls the JARVIS Telegram bot.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":  {"type": "STRING", "description": "start | stop | setup | notify | status"},
                "message": {"type": "STRING"},
            },
            "required": ["action"]
        }
    },

    {
        "name": "terabox_backup",
        "description": (
            "Starts, stops, or checks Jarvis's Telegram-to-TeraBox backup "
            "userbot. Starting it resumes live backups for registered chats."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "start | stop | status | help",
                },
            },
            "required": ["action"],
        },
    },

    # ── Social Login ──────────────────────────────────────────────────────────
    {
        "name": "social_login",
        "description": "Connect social accounts (instagram, twitter, facebook, linkedin, tiktok) via a real browser session. action='login' opens a visible window where the user signs in with their normal username + password + 2FA; the session is saved locally and reused — no stored passwords. Also: status, logout, list.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":   {"type": "STRING"},
                "platform": {"type": "STRING"},
                "browser":  {"type": "STRING"},
                "username": {"type": "STRING"},
                "password": {"type": "STRING"},
                "force":    {"type": "BOOLEAN"},
            },
            "required": ["action"]
        }
    },

    # ── Trading Agent ─────────────────────────────────────────────────────────
    {
        "name": "trading_agent",
        "description": "Professional ICT trading engine with MT5.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":       {"type": "STRING", "description": "analyse | scan | watchlist | trade | connect | disconnect | positions | account | close | modify | performance | risk_status | session | fibonacci | risk_calc | save_credentials | full_report"},
                "symbol":       {"type": "STRING"},
                "timeframe":    {"type": "STRING"},
                "bias_tf":      {"type": "STRING"},
                "htf":          {"type": "BOOLEAN"},
                "symbols":      {"type": "ARRAY", "items": {"type": "STRING"}},
                "min_score":    {"type": "NUMBER"},
                "risk_percent": {"type": "NUMBER"},
                "ticket":       {"type": "INTEGER"},
                "percent":      {"type": "NUMBER"},
                "new_sl":       {"type": "NUMBER"},
                "new_tp":       {"type": "NUMBER"},
                "mt5_login":    {"type": "INTEGER"},
                "mt5_password": {"type": "STRING"},
                "mt5_server":   {"type": "STRING"},
                "broker":       {"type": "STRING"},
                "high":         {"type": "NUMBER"},
                "low":          {"type": "NUMBER"},
                "direction":    {"type": "STRING"},
                "account_size": {"type": "NUMBER"},
                "entry":        {"type": "NUMBER"},
                "stop_loss":    {"type": "NUMBER"},
                "exchange":     {"type": "STRING"},
                "period":       {"type": "STRING"},
            },
            "required": ["action"]
        }
    },

    # ── Number Tracer ─────────────────────────────────────────────────────────
    {
        "name": "number_tracer",
        "description": "Phone number investigation.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING"},
                "phone":  {"type": "STRING"},
                "number": {"type": "STRING"},
            },
            "required": ["phone"]
        }
    },

    # ── Smart Home ────────────────────────────────────────────────────────────
    {
        "name": "smart_home",
        "description": "Controls smart home devices.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING"},
                "device":      {"type": "STRING"},
                "room":        {"type": "STRING"},
                "brightness":  {"type": "INTEGER"},
                "color":       {"type": "STRING"},
                "temperature": {"type": "NUMBER"},
                "scene":       {"type": "STRING"},
                "topic":       {"type": "STRING"},
                "payload":     {"type": "STRING"},
            },
            "required": ["action"]
        }
    },

    # ── Web Search ────────────────────────────────────────────────────────────
    {
        "name": "web_search",
        "description": "Searches the web.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":  {"type": "STRING"},
                "mode":   {"type": "STRING"},
                "items":  {"type": "ARRAY", "items": {"type": "STRING"}},
                "aspect": {"type": "STRING"},
            },
            "required": ["query"]
        }
    },

    # ── Weather ───────────────────────────────────────────────────────────────
    {
        "name": "weather_report",
        "description": "Weather report.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING"}
            },
            "required": ["city"]
        }
    },

    # ── Send Message ──────────────────────────────────────────────────────────
    {
        "name": "send_message",
        "description": "Sends a text message.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "receiver":     {"type": "STRING"},
                "message_text": {"type": "STRING"},
                "platform":     {"type": "STRING"},
            },
            "required": ["receiver", "message_text", "platform"]
        }
    },

    # ── Reminder ──────────────────────────────────────────────────────────────
    {
        "name": "reminder",
        "description": "Sets a timed reminder.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date":    {"type": "STRING"},
                "time":    {"type": "STRING"},
                "message": {"type": "STRING"},
            },
            "required": ["date", "time", "message"]
        }
    },

    # ── Notes Agent ───────────────────────────────────────────────────────────
    {
        "name": "notes_agent",
        "description": "Save, search, list, read, update, and delete personal notes. Actions: add, search, list, read, update, delete.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING"},
                "text":   {"type": "STRING"},
                "title":  {"type": "STRING"},
                "tags":   {"type": "STRING"},
                "query":  {"type": "STRING"},
                "id":     {"type": "INTEGER"},
                "limit":  {"type": "INTEGER"},
                "tag":    {"type": "STRING"},
            },
            "required": ["action"]
        }
    },

    # ── System Monitor ────────────────────────────────────────────────────────
    {
        "name": "system_agent",
        "description": "Report PC health: CPU, RAM, disk, battery, uptime, network, top processes. Actions: status, cpu, memory, disk, battery, network, processes, uptime.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING"},
                "count":  {"type": "INTEGER"},
                "sort":   {"type": "STRING"},
            },
            "required": ["action"]
        }
    },

    # ── Daily Briefing ────────────────────────────────────────────────────────
    {
        "name": "briefing_agent",
        "description": "Deliver a spoken daily briefing (greeting, weather, unread email, system health, news). Use for good morning / brief me.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":   {"type": "STRING"},
                "city":     {"type": "STRING"},
                "topic":    {"type": "STRING"},
                "sections": {"type": "STRING"},
            },
            "required": []
        }
    },


    # ── Scope / Rules of Engagement ───────────────────────────────────────────
    {
        "name": "scope_agent",
        "description": "Manage authorized pentest scope (Rules of Engagement). Actions: add, remove, list, check, authorize. Fail-closed authorization check for targets.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":        {"type": "STRING"},
                "target":        {"type": "STRING"},
                "note":          {"type": "STRING"},
                "authorized_by": {"type": "STRING"},
                "notes":         {"type": "STRING"},
            },
            "required": ["action"]
        }
    },

    # ── Findings Tracker ──────────────────────────────────────────────────────
    {
        "name": "findings_agent",
        "description": "Track pentest findings (severity, CVSS, target, remediation, status). Actions: add, list, get, update, delete, summary.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING"},
                "title":       {"type": "STRING"},
                "severity":    {"type": "STRING"},
                "cvss":        {"type": "NUMBER"},
                "target":      {"type": "STRING"},
                "description": {"type": "STRING"},
                "remediation": {"type": "STRING"},
                "status":      {"type": "STRING"},
                "id":          {"type": "INTEGER"},
            },
            "required": ["action"]
        }
    },

    # ── Pentest Report Generator ──────────────────────────────────────────────
    {
        "name": "report_agent",
        "description": "Generate a professional pentest report (Markdown) from recorded findings and authorized scope. Actions: generate, preview.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":   {"type": "STRING"},
                "title":    {"type": "STRING"},
                "author":   {"type": "STRING"},
                "client":   {"type": "STRING"},
                "filename": {"type": "STRING"},
            },
            "required": []
        }
    },

    # ── Google connection (OAuth for Gmail/Calendar/Docs/Drive) ──────────────
    {
        "name": "google_auth",
        "description": "Connect or manage the Google account used by Gmail, Calendar, Docs and Drive agents. Actions: connect, status, logout, setup.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING"},
            },
            "required": []
        }
    },

    # ── Gmail (official API) ─────────────────────────────────────────────────
    {
        "name": "gmail_agent",
        "description": "Gmail via the official Google API. Actions: unread, list, search, read, send, labels, setup. Requires 'connect google' first.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":  {"type": "STRING"},
                "query":   {"type": "STRING"},
                "id":      {"type": "STRING"},
                "to":      {"type": "STRING"},
                "subject": {"type": "STRING"},
                "body":    {"type": "STRING"},
                "limit":   {"type": "INTEGER"},
            },
            "required": []
        }
    },

    # ── Google Calendar ──────────────────────────────────────────────────────
    {
        "name": "calendar_agent",
        "description": "Google Calendar scheduling. Actions: today, upcoming, create, delete, setup. Times in ISO format; default timezone Africa/Nairobi.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":           {"type": "STRING"},
                "summary":          {"type": "STRING"},
                "start":            {"type": "STRING"},
                "end":              {"type": "STRING"},
                "description":      {"type": "STRING"},
                "location":         {"type": "STRING"},
                "id":               {"type": "STRING"},
                "days":             {"type": "INTEGER"},
                "duration_minutes": {"type": "INTEGER"},
            },
            "required": []
        }
    },

    # ── Google Docs ──────────────────────────────────────────────────────────
    {
        "name": "docs_agent",
        "description": "Google Docs: create, read, append, and export_report (push a pentest report into a shareable Doc). Actions: create, read, append, export_report, setup.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING"},
                "title":  {"type": "STRING"},
                "text":   {"type": "STRING"},
                "id":     {"type": "STRING"},
                "client": {"type": "STRING"},
            },
            "required": []
        }
    },

    # ── Google Drive ─────────────────────────────────────────────────────────
    {
        "name": "drive_agent",
        "description": "Google Drive file management. Actions: list, search, upload, download, setup. Uploads use the drive.file scope (JARVIS-created files only).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING"},
                "query":     {"type": "STRING"},
                "path":      {"type": "STRING"},
                "name":      {"type": "STRING"},
                "id":        {"type": "STRING"},
                "dest":      {"type": "STRING"},
                "folder_id": {"type": "STRING"},
                "limit":     {"type": "INTEGER"},
            },
            "required": []
        }
    },

    # ── Notion ───────────────────────────────────────────────────────────────
    {
        "name": "notion_agent",
        "description": "Notion workspace: search, create_page, append, and sync_findings (push pentest findings to Notion). Actions: setup, status, search, create_page, append, sync_findings.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":         {"type": "STRING"},
                "token":          {"type": "STRING"},
                "parent_page_id": {"type": "STRING"},
                "database_id":    {"type": "STRING"},
                "query":          {"type": "STRING"},
                "title":          {"type": "STRING"},
                "content":        {"type": "STRING"},
                "text":           {"type": "STRING"},
                "id":             {"type": "STRING"},
            },
            "required": []
        }
    },

        # ── GitHub Agent (Cross-Platform Universal Tool Manager) ─────────────────
    {
        "name": "github_agent",
        "description": (
            "Universal cross-platform GitHub Tool Manager. Can clone any GitHub repo. "
            "When given a task (phishing, mega download, recon, etc.), it scans all "
            "cloned tools, selects the best one, runs it, and returns clean results. "
            "Works on Linux, macOS, and Windows (with graceful degradation)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "clone | clone_and_install | use | run | execute"},
                "repo": {"type": "STRING", "description": "GitHub URL or owner/repo"},
                "request": {"type": "STRING", "description": "Natural language request e.g. 'phish with Google' or 'download from mega'"},
                "template": {"type": "STRING", "description": "Zphisher template number"},
                "target_url": {"type": "STRING", "description": "Target URL for tools"},
                "mega_link": {"type": "STRING", "description": "Full mega.nz link"},
            },
            "required": ["action"]
        }
    },

    # ── YouTube ───────────────────────────────────────────────────────────────
    {
        "name": "youtube_video",
        "description": "Controls YouTube.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING"},
                "query":  {"type": "STRING"},
                "save":   {"type": "BOOLEAN"},
                "region": {"type": "STRING"},
                "url":    {"type": "STRING"},
            },
            "required": []
        }
    },

    # ── Screen Process ────────────────────────────────────────────────────────
    {
        "name": "screen_process",
        "description": "Captures and analyzes screen or webcam. Stay SILENT after calling.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING"},
                "text":  {"type": "STRING"},
            },
            "required": ["text"]
        }
    },

    # ── Computer Settings ─────────────────────────────────────────────────────
    {
        "name": "computer_settings",
        "description": "Controls computer: volume, brightness, WiFi, shortcuts.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING"},
                "description": {"type": "STRING"},
                "value":       {"type": "STRING"},
            },
            "required": []
        }
    },

    # ── Browser Control ───────────────────────────────────────────────────────
    {
        "name": "browser_control",
        "description": "Controls web browser.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING"},
                "browser":     {"type": "STRING"},
                "url":         {"type": "STRING"},
                "query":       {"type": "STRING"},
                "engine":      {"type": "STRING"},
                "selector":    {"type": "STRING"},
                "text":        {"type": "STRING"},
                "description": {"type": "STRING"},
                "direction":   {"type": "STRING"},
                "amount":      {"type": "INTEGER"},
                "key":         {"type": "STRING"},
                "path":        {"type": "STRING"},
                "incognito":   {"type": "BOOLEAN"},
                "clear_first": {"type": "BOOLEAN"},
            },
            "required": ["action"]
        }
    },

    # ── File Controller ───────────────────────────────────────────────────────
    {
        "name": "file_controller",
        "description": "Manages files and folders.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING"},
                "path":        {"type": "STRING"},
                "destination": {"type": "STRING"},
                "new_name":    {"type": "STRING"},
                "content":     {"type": "STRING"},
                "name":        {"type": "STRING"},
                "extension":   {"type": "STRING"},
                "count":       {"type": "INTEGER"},
            },
            "required": ["action"]
        }
    },

    # ── Desktop Control ───────────────────────────────────────────────────────
    {
        "name": "desktop_control",
        "description": "Controls the desktop.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING"},
                "path":   {"type": "STRING"},
                "url":    {"type": "STRING"},
                "mode":   {"type": "STRING"},
                "task":   {"type": "STRING"},
            },
            "required": ["action"]
        }
    },

    # ── Code Helper ───────────────────────────────────────────────────────────
    {
        "name": "code_helper",
        "description": "Writes, edits, explains, runs code.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING"},
                "description": {"type": "STRING"},
                "language":    {"type": "STRING"},
                "output_path": {"type": "STRING"},
                "file_path":   {"type": "STRING"},
                "code":        {"type": "STRING"},
                "args":        {"type": "STRING"},
                "timeout":     {"type": "INTEGER"},
            },
            "required": ["action"]
        }
    },

    # ── Dev Agent ─────────────────────────────────────────────────────────────
    {
        "name": "dev_agent",
        "description": "Builds complete multi-file projects.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "description":  {"type": "STRING"},
                "language":     {"type": "STRING"},
                "project_name": {"type": "STRING"},
                "timeout":      {"type": "INTEGER"},
            },
            "required": ["description"]
        }
    },

    # ── Agent Task ────────────────────────────────────────────────────────────
    {
        "name": "agent_task",
        "description": "Executes complex multi-step tasks via AI Planner. DO NOT use for single commands.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "goal":     {"type": "STRING"},
                "priority": {"type": "STRING"},
            },
            "required": ["goal"]
        }
    },

    # ── Computer Control ──────────────────────────────────────────────────────
    {
        "name": "computer_control",
        "description": "Direct computer control: type, click, hotkeys, scroll, mouse, screenshots, run_command.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING",  "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | drag | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click | random_data | user_data | run_command | shell"},
                "text":        {"type": "STRING"},
                "command":     {"type": "STRING"},
                "x":           {"type": "INTEGER"},
                "y":           {"type": "INTEGER"},
                "keys":        {"type": "STRING"},
                "key":         {"type": "STRING"},
                "direction":   {"type": "STRING"},
                "amount":      {"type": "INTEGER"},
                "seconds":     {"type": "NUMBER"},
                "title":       {"type": "STRING"},
                "description": {"type": "STRING"},
                "type":        {"type": "STRING"},
                "field":       {"type": "STRING"},
                "clear_first": {"type": "BOOLEAN"},
                "path":        {"type": "STRING"},
                "timeout":     {"type": "INTEGER"},
            },
            "required": ["action"]
        }
    },

    # ── Bluetooth Agent ───────────────────────────────────────────────────────
    {
        "name": "bluetooth_agent",
        "description": "Controls Bluetooth.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":   {"type": "STRING"},
                "device":   {"type": "STRING"},
                "duration": {"type": "INTEGER"},
            },
            "required": ["action"]
        }
    },

    # ── Game Updater ──────────────────────────────────────────────────────────
    {
        "name": "game_updater",
        "description": "Steam/Epic Games tool.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":            {"type": "STRING"},
                "platform":          {"type": "STRING"},
                "game_name":         {"type": "STRING"},
                "app_id":            {"type": "STRING"},
                "hour":              {"type": "INTEGER"},
                "minute":            {"type": "INTEGER"},
                "shutdown_when_done":{"type": "BOOLEAN"},
            },
            "required": []
        }
    },

    # ── Flight Finder ─────────────────────────────────────────────────────────
    {
        "name": "flight_finder",
        "description": "Searches Google Flights.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "origin":      {"type": "STRING"},
                "destination": {"type": "STRING"},
                "date":        {"type": "STRING"},
                "return_date": {"type": "STRING"},
                "passengers":  {"type": "INTEGER"},
                "cabin":       {"type": "STRING"},
                "save":        {"type": "BOOLEAN"},
            },
            "required": ["origin", "destination", "date"]
        }
    },

    # ── Credential Manager ────────────────────────────────────────────────────
    {
        "name": "credential_manager",
        "description": "Manages credentials and API keys.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":  {"type": "STRING"},
                "service": {"type": "STRING"},
                "key":     {"type": "STRING"},
                "value":   {"type": "STRING"},
            },
            "required": ["action"]
        }
    },

    # ── Shutdown ──────────────────────────────────────────────────────────────
    {
        "name": "shutdown_jarvis",
        "description": "Shuts down JARVIS completely.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },

    # ── File Processor ────────────────────────────────────────────────────────
    {
        "name": "file_processor",
        "description": "Processes any uploaded file.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "file_path":   {"type": "STRING"},
                "action":      {"type": "STRING"},
                "instruction": {"type": "STRING"},
                "format":      {"type": "STRING"},
                "width":       {"type": "INTEGER"},
                "height":      {"type": "INTEGER"},
                "scale":       {"type": "NUMBER"},
                "quality":     {"type": "INTEGER"},
                "start":       {"type": "STRING"},
                "end":         {"type": "STRING"},
                "timestamp":   {"type": "STRING"},
                "column":      {"type": "STRING"},
                "value":       {"type": "STRING"},
                "condition":   {"type": "STRING"},
                "ascending":   {"type": "BOOLEAN"},
                "save":        {"type": "BOOLEAN"},
                "destination": {"type": "STRING"},
            },
            "required": []
        }
    },

    # ── Save Memory ───────────────────────────────────────────────────────────
    {
        "name": "save_memory",
        "description": "Save personal fact to long-term memory. Do NOT announce.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {"type": "STRING"},
                "key":      {"type": "STRING"},
                "value":    {"type": "STRING"},
            },
            "required": ["category", "key", "value"]
        }
    },

    # ── Recall Memory (Brain 2.0) ─────────────────────────────────────────────
    {
        "name": "recall_memory",
        "description": "Search long-term memory for past facts, preferences, or previous task results. Use when the user asks what you remember or references earlier context.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING"},
                "limit": {"type": "INTEGER"},
            },
            "required": ["query"]
        }
    },

    # ── Email Agent ───────────────────────────────────────────────────────────
    {
        "name": "email_agent",
        "description": "Manages email through a real browser session (default). The user runs action='login' once and signs in with their normal email + password (and 2FA) in a visible window; the session is saved locally and reused — no app password needed. Then check/search/send. Use backend='imap' for the legacy IMAP/SMTP path.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING"},
                "to":          {"type": "STRING"},
                "subject":     {"type": "STRING"},
                "body":        {"type": "STRING"},
                "keyword":     {"type": "STRING"},
                "count":       {"type": "INTEGER"},
                "email_id":    {"type": "STRING"},
                "account":     {"type": "STRING"},
                "interval":    {"type": "INTEGER"},
                "unread_only": {"type": "BOOLEAN"},
                "email":       {"type": "STRING"},
                "password":    {"type": "STRING"},
                "name":        {"type": "STRING"},
                "backend":     {"type": "STRING"},
                "provider":    {"type": "STRING"},
                "index":       {"type": "INTEGER"},
            },
            "required": ["action"]
        }
    },

    # ── Social Agent ──────────────────────────────────────────────────────────
    {
        "name": "social_agent",
        "description": "Manages social media.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "platform": {"type": "STRING"},
                "action":   {"type": "STRING"},
                "content":  {"type": "STRING"},
                "username": {"type": "STRING"},
                "url":      {"type": "STRING"},
                "query":    {"type": "STRING"},
                "browser":  {"type": "STRING"},
            },
            "required": ["platform", "action"]
        }
    },

    # ── Dev Forge ─────────────────────────────────────────────────────────────
    {
        "name": "dev_forge",
        "description": "Builds complete software projects.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "task":        {"type": "STRING"},
                "language":    {"type": "STRING"},
                "ide":         {"type": "STRING"},
                "open_ide":    {"type": "BOOLEAN"},
                "max_retries": {"type": "INTEGER"},
                "project_dir": {"type": "STRING"},
            },
            "required": ["task"]
        }
    },

    # ── Network Scan ──────────────────────────────────────────────────────────
    {
        "name": "network_scan",
        "description": "Scans local network with GUI.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "network":     {"type": "STRING"},
                "generate_qr": {"type": "BOOLEAN"},
            },
            "required": []
        }
    },
]


# ── Tool Declaration Compressor ───────────────────────────────────────────────
def _compress_tool_declarations(declarations: list) -> list:
    MAX_DESC_LEN    = 180
    MAX_PARAM_DESC  = 80
    MAX_ACTION_DESC = 280

    compressed = []
    for tool in declarations:
        try:
            t = {
                "name":        tool["name"],
                "description": tool.get("description", "")[:MAX_DESC_LEN],
                "parameters":  {}
            }
            orig_params = tool.get("parameters", {})
            if not orig_params:
                t["parameters"] = orig_params
                compressed.append(t)
                continue

            new_params = {
                "type":     orig_params.get("type", "OBJECT"),
                "required": orig_params.get("required", []),
            }
            new_props = {}
            for prop_name, prop_info in orig_params.get("properties", {}).items():
                prop_desc = prop_info.get("description", "")
                if prop_name == "action":
                    prop_desc = prop_desc[:MAX_ACTION_DESC]
                else:
                    prop_desc = prop_desc[:MAX_PARAM_DESC]
                new_prop = {"type": prop_info.get("type", "STRING")}
                if prop_desc:
                    new_prop["description"] = prop_desc
                if prop_info.get("type") == "ARRAY" and "items" in prop_info:
                    new_prop["items"] = prop_info["items"]
                new_props[prop_name] = new_prop

            new_params["properties"] = new_props
            t["parameters"] = new_params
            compressed.append(t)
        except Exception as e:
            print(f"[JARVIS] ⚠️ Compress error for {tool.get('name')}: {e}")
            compressed.append(tool)

    print(f"[JARVIS] 🗜️ Tools compressed: {len(compressed)}")
    return compressed


# ── Helpers ───────────────────────────────────────────────────────────────────
def _smart_timeout(target: str, base: int = 120) -> int:
    if not target:
        return base
    if "/" in target:
        try:
            prefix = int(target.split("/")[1])
            if prefix <= 16: return max(base, 600)
            elif prefix <= 24: return max(base, 300)
        except Exception: pass
    return base


NMAP_FALLBACK_CHAIN = [
    ("nmap_full", ""),
    ("nmap_scan", "-p 22,80,443,8080,8443,3306,5432,6379,27017 --open"),
    ("nmap_scan", "-p 1-1000 --open -T3"),
    ("nmap_scan", "-p 80,443 --open -T2"),
    ("ping", ""),
]


def _truncate_result(result: str, tool_name: str) -> str:
    if not isinstance(result, str):
        result = str(result)
    if len(result) <= MAX_TOOL_RESPONSE:
        return result

    if tool_name in ("kali_agent", "phantom_agent"):
        try:
            groq_key = _get_groq_api_key()
            if groq_key:
                from groq import Groq as _Groq
                client = _Groq(api_key=groq_key)
                resp   = client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You summarize pentesting tool output for a voice AI. "
                                "Extract ONLY the most critical findings: "
                                "open ports, services, vulnerabilities, "
                                "credentials, hashes, key results, errors. "
                                "Be extremely concise. Max 300 words. "
                                "Start directly with findings."
                            ),
                        },
                        {
                            "role": "user",
                            "content": f"Summarize:\n\n{result[:6000]}",
                        },
                    ],
                    max_tokens=500,
                    temperature=0.1,
                )
                summary  = resp.choices[0].message.content.strip()
                full_len = len(result)
                return (
                    f"{summary}\n\n"
                    f"[📁 Full output: {full_len:,} chars]"
                )
        except Exception as e:
            print(f"[JARVIS] Groq summarization failed: {e}")

    head = result[:900]
    tail = result[-400:]
    mid  = f"\n\n[... {len(result) - 1300:,} chars truncated ...]\n\n"
    return head + mid + tail


class JarvisLive:

    def __init__(self, ui: JarvisUI):
        self.ui               = ui
        self.session          = None
        self.audio_in_queue   = None
        self.out_queue        = None
        self._loop            = None
        self._is_speaking     = False
        self._speaking_lock   = threading.Lock()
        self.ui.on_text_command = self._on_text_command
        self._turn_done_event: asyncio.Event | None = None

    def _on_text_command(self, text: str):
        if not self._loop or not self.session: return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ), self._loop
        )

    def set_speaking(self, value: bool):
        with self._speaking_lock: self._is_speaking = value
        if value: self.ui.set_state("SPEAKING")
        elif not self.ui.muted: self.ui.set_state("LISTENING")

    def speak(self, text: str):
        if not self._loop or not self.session: return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ), self._loop
        )

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime
        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()
        now        = datetime.now()
        time_str   = now.strftime("%A, %B %d, %Y — %I:%M %p")
        time_ctx   = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )
        parts = [time_ctx]
        if mem_str: parts.append(mem_str)
        try:
            lt_mem = lt_format(lt_preferences(limit=10) + lt_recent(limit=5))
            if lt_mem: parts.append(lt_mem)
        except Exception:
            pass
        parts.append(sys_prompt)

        compressed = _compress_tool_declarations(TOOL_DECLARATIONS)

        return types.LiveConnectConfig(
            response_modalities        = ["AUDIO"],
            output_audio_transcription = {},
            input_audio_transcription  = {},
            system_instruction         = "\n".join(parts),
            tools                      = [{"function_declarations": compressed}],
            session_resumption         = types.SessionResumptionConfig(),
            thinking_config            = types.ThinkingConfig(thinking_budget=0),
            speech_config              = types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Charon"
                    )
                )
            ),
        )

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})
        print(f"[JARVIS] 🔧 {name}  {args}")
        self.ui.set_state("THINKING")

        if name == "save_memory":
            category = args.get("category", "notes")
            key, value = args.get("key", ""), args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
                try:
                    lt_remember(f"{key}: {value}", kind="preference",
                                category=category, key=key, source="voice",
                                importance=0.8)
                except Exception:
                    pass
                print(f"[Memory] 💾 {category}/{key} = {value}")
            if not self.ui.muted: self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
            )

        if name == "recall_memory":
            query = args.get("query", "")
            try:
                limit = int(args.get("limit", 5) or 5)
            except (TypeError, ValueError):
                limit = 5
            try:
                items = lt_recall(query, limit=limit)
                text  = lt_format(items) or "No matching memories, sir."
            except Exception as e:
                text = f"Memory lookup failed: {e}"
            if not self.ui.muted: self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": text}
            )

        loop   = asyncio.get_event_loop()
        result = "Done."

        try:

            # ── Kali Agent ────────────────────────────────────────────────────
            if name == "kali_agent":
                args["api_key"]      = _get_api_key()
                args["groq_api_key"] = _get_groq_api_key()
                try:
                    r = await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            lambda: kali_agent(
                                parameters=args,
                                player=self.ui,
                                speak=self.speak,
                            )
                        ),
                        timeout=KALI_AGENT_TIMEOUT,
                    )
                    result = r or "Done."
                except asyncio.TimeoutError:
                    action_name = args.get("action", "task")
                    target_name = args.get("target", "")
                    result = (
                        f"The {action_name} operation"
                        f"{' on ' + target_name if target_name else ''} "
                        f"is running in the background, sir. "
                        f"Initial steps have been executed."
                    )
                    self.ui.write_log(
                        "[KALI] ⏱️ Response timeout — running in background"
                    )

            # ── Phantom Agent ─────────────────────────────────────────────────
            elif name == "phantom_agent":
                args["api_key"]      = _get_api_key()
                args["groq_api_key"] = _get_groq_api_key()
                try:
                    r = await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            lambda: phantom_agent(
                                parameters=args,
                                player=self.ui,
                                speak=self.speak,
                            )
                        ),
                        timeout=PHANTOM_AGENT_TIMEOUT,
                    )
                    result = r or "Phantom operation completed."
                except asyncio.TimeoutError:
                    p_action = args.get("action", "operation")
                    p_target = (
                        args.get("person") or
                        args.get("target") or
                        args.get("company") or
                        args.get("network") or
                        "target"
                    )
                    result = (
                        f"Phantom Agent {p_action} against {p_target} "
                        f"is running in the background sir. "
                        f"This is a heavy autonomous operation. "
                        f"Results are being logged to the phantom reports directory."
                    )
                    self.ui.write_log(
                        f"[PHANTOM] ⏳ Operation in background "
                        f"(timeout={PHANTOM_AGENT_TIMEOUT}s)"
                    )
                except Exception as ph_err:
                    result = f"Phantom Agent error: {ph_err}"
                    self.speak_error("phantom_agent", str(ph_err))
                    traceback.print_exc()

            # ── Red Team Agent ─────────────────────────────────────────────────
            elif name == "red_team_agent":
                args["api_key"]      = _get_api_key()
                args["groq_api_key"] = _get_groq_api_key()
                try:
                    r = await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            lambda: red_team_agent(
                                parameters=args,
                                player=self.ui,
                                speak=self.speak,
                            )
                        ),
                        timeout=PHANTOM_AGENT_TIMEOUT,
                    )
                    result = r or "Red Team operation completed."
                except asyncio.TimeoutError:
                    rt_action = args.get("action", "operation")
                    rt_target = (
                        args.get("person") or
                        args.get("target") or
                        args.get("company") or
                        args.get("network") or
                        "target"
                    )
                    result = (
                        f"Red Team Agent {rt_action} against {rt_target} "
                        f"is running in the background sir. "
                        f"This is a heavy autonomous operation. "
                        f"Results are being logged to the phantom reports directory."
                    )
                    self.ui.write_log(
                        f"[RED TEAM] ⏳ Operation in background "
                        f"(timeout={PHANTOM_AGENT_TIMEOUT}s)"
                    )
                except Exception as rt_err:
                    result = f"Red Team Agent error: {rt_err}"
                    self.speak_error("red_team_agent", str(rt_err))
                    traceback.print_exc()


            elif name == "ict_trader":
                r = await loop.run_in_executor(
                    None,
                    lambda: ict_trader_action(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                )
                )
                result = r or "Done."


            # ── Handler (add to _execute_tool in JarvisLive) ──────────────────────────
            elif name == "prompt_engineer":
                r = await loop.run_in_executor(
                    None,
                    lambda: prompt_engineer(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak,
                )
                )
                result = r or "Done."



            # ── Open App ──────────────────────────────────────────────────────
            elif name == "open_app":
                r = await loop.run_in_executor(
                    None,
                    lambda: open_app(
                        parameters=args, response=None, player=self.ui
                    )
                )
                result = r or f"Opened {args.get('app_name')}."

            # ── Weather ───────────────────────────────────────────────────────
            elif name == "weather_report":
                r = await loop.run_in_executor(
                    None,
                    lambda: weather_action(parameters=args, player=self.ui)
                )
                result = r or "Weather delivered."

            # ── Browser Control ───────────────────────────────────────────────
            elif name == "browser_control":
                r = await loop.run_in_executor(
                    None,
                    lambda: browser_control(parameters=args, player=self.ui)
                )
                result = r or "Done."

            # ── File Controller ───────────────────────────────────────────────
            elif name == "file_controller":
                r = await loop.run_in_executor(
                    None,
                    lambda: file_controller(parameters=args, player=self.ui)
                )
                result = r or "Done."

            # ── Send Message ──────────────────────────────────────────────────
            elif name == "send_message":
                r = await loop.run_in_executor(
                    None,
                    lambda: send_message(
                        parameters=args, response=None,
                        player=self.ui, session_memory=None
                    )
                )
                result = r or f"Message sent to {args.get('receiver')}."

            # ── Reminder ──────────────────────────────────────────────────────
            elif name == "reminder":
                r = await loop.run_in_executor(
                    None,
                    lambda: reminder(
                        parameters=args, response=None, player=self.ui
                    )
                )
                result = r or "Reminder set."
            

             # ── Overseer ──────────────────────────────────────────────────────
            elif name == "overseer":
                r = await loop.run_in_executor(
                    None,
                    lambda: overseer(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."


            # ── YouTube ───────────────────────────────────────────────────────
            elif name == "youtube_video":
                r = await loop.run_in_executor(
                    None,
                    lambda: youtube_video(
                        parameters=args, response=None, player=self.ui
                    )
                )
                result = r or "Done."

            # ── TikTok Agent ──────────────────────────────────────────────────
            elif name == "tiktok_agent":
                r = await loop.run_in_executor(
                    None,
                    lambda: tiktok_agent(
                        parameters=args, player=self.ui, speak=self.speak
                    )
                )
                result = r or "Done."

            elif name == "vortex_pirate":
                r = await loop.run_in_executor(
                    None,
                    lambda: vortex_pirate(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."
            
            elif name == "instagram_agent":
                 r = await loop.run_in_executor(
                    None,
                    lambda: instagram_agent(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                 result = r or "Instagram action completed."

            # ── Screen Process ────────────────────────────────────────────────
            elif name == "screen_process":
                threading.Thread(
                    target=screen_process,
                    kwargs={
                        "parameters":    args,
                        "response":      None,
                        "player":        self.ui,
                        "session_memory":None,
                    },
                    daemon=True
                ).start()
                result = (
                    "Vision module activated. "
                    "Stay completely silent — "
                    "vision module will speak directly."
                )

            # ── Computer Settings ─────────────────────────────────────────────
            elif name == "computer_settings":
                r = await loop.run_in_executor(
                    None,
                    lambda: computer_settings(
                        parameters=args, response=None, player=self.ui
                    )
                )
                result = r or "Done."

            # ── GitHub Agent (Cross-Platform) ─────────────────────────────────
            elif name == "github_agent":
                r = await loop.run_in_executor(
                    None,
                    lambda: github_agent(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            # ── Desktop Control ───────────────────────────────────────────────
            elif name == "desktop_control":
                r = await loop.run_in_executor(
                    None,
                    lambda: desktop_control(
                        parameters=args, player=self.ui
                    )
                )
                result = r or "Done."

            # ── Code Helper ───────────────────────────────────────────────────
            elif name == "code_helper":
                r = await loop.run_in_executor(
                    None,
                    lambda: code_helper(
                        parameters=args, player=self.ui, speak=self.speak
                    )
                )
                result = r or "Done."

            # ── Dev Agent ─────────────────────────────────────────────────────
            elif name == "dev_agent":
                r = await loop.run_in_executor(
                    None,
                    lambda: dev_agent(
                        parameters=args, player=self.ui, speak=self.speak
                    )
                )
                result = r or "Done."

            # ── Agent Task ────────────────────────────────────────────────────
            elif name == "agent_task":
                goal = args.get("goal", "")
                self.ui.write_log(f"SYS: Planning: {goal[:80]}")
                self.speak(f"Formulating plan, sir. Goal: {goal[:80]}")

                async def _run_autonomous():
                    planner = JarvisPlanner(
                        _get_api_key(), TOOL_DECLARATIONS
                    )
                    plan = await planner.create_plan(goal)
                    if not plan:
                        return "Could not generate a plan."
                    self.ui.write_log(
                        f"SYS: {len(plan)} steps. Executing..."
                    )
                    self.speak(
                        f"Plan ready — {len(plan)} steps. "
                        f"Executing now, sir."
                    )
                    engine = ExecutionEngine(self, planner)
                    exec_results = await engine.execute_plan(
                        plan, goal=goal, allow_replan=True
                    )
                    summary = engine.get_summary()
                    self.speak(
                        f"Task complete, sir. "
                        f"{len(exec_results)} steps executed."
                    )
                    return (
                        f"Done. {len(exec_results)} steps.\n{summary}"
                    )

                result = await _run_autonomous()

            # ── Evolution Engine ──────────────────────────────────────────────
            elif name == "evolution_engine":
                action      = args.get("action", "list")
                requirement = args.get("requirement", "")
                tool_name   = args.get("tool_name", "")
                params_json = args.get("parameters_json", "{}")
                evo         = get_evolution_engine(_get_api_key())

                if action == "generate":
                    if not requirement:
                        try:
                            parsed = (
                                json.loads(params_json)
                                if params_json else {}
                            )
                            requirement = (
                                parsed.get("requirement", "")
                                or parsed.get("description", "")
                                or parsed.get("task", "")
                            )
                        except Exception:
                            pass
                    if not requirement and tool_name and len(tool_name) > 20:
                        requirement = tool_name
                    if not requirement:
                        for k, v in args.items():
                            if (isinstance(v, str) and len(v) > 20
                                    and k not in ("action", "tool_name")):
                                requirement = v
                                break
                    if not requirement:
                        result = (
                            "Please provide a requirement. "
                            "Say: build a tool that [description]"
                        )
                    else:
                        self.ui.write_log(
                            f"[EVO] Building: {requirement[:80]}"
                        )
                        gen_result = await evo.generate_tool(
                            requirement=requirement,
                            tool_name=tool_name or None,
                            speak=self.speak,
                            player=self.ui
                        )
                        if gen_result["success"]:
                            _, decl = evo.hot_load(gen_result["tool_name"])
                            if decl:
                                TOOL_DECLARATIONS.append(decl)
                            result = (
                                f"New tool built: {gen_result['tool_name']}\n"
                                f"Description: {gen_result['description']}\n"
                                f"Path: {gen_result['path']}"
                            )
                        else:
                            result = (
                                f"Generation failed: "
                                f"{gen_result.get('error')}"
                            )

                elif action == "list":
                    result = evo.list_evolved_tools()
                elif action == "delete":
                    result = evo.delete_evolved_tool(tool_name)
                elif action == "reload":
                    decls = evo.hot_load_all()
                    for d in decls:
                        if d not in TOOL_DECLARATIONS:
                            TOOL_DECLARATIONS.append(d)
                    result = f"Reloaded {len(decls)} evolved tools."
                elif action == "install_deps":
                    if not tool_name:
                        result = "Please specify tool_name."
                    else:
                        r = await loop.run_in_executor(
                            None,
                            lambda: evo.install_tool_deps(
                                tool_name, player=self.ui
                            )
                        )
                        result = r or "Done."
                elif action == "call":
                    try:
                        params = (
                            json.loads(params_json)
                            if params_json else {}
                        )
                    except Exception:
                        params = {}
                    r = await loop.run_in_executor(
                        None,
                        lambda: evo.call_evolved_tool(
                            tool_name, params,
                            player=self.ui, speak=self.speak
                        )
                    )
                    result = r or "Done."
                else:
                    result = f"Unknown evolution action: {action}"

            # ── Web Search ────────────────────────────────────────────────────
            elif name == "web_search":
                r = await loop.run_in_executor(
                    None,
                    lambda: web_search_action(
                        parameters=args, player=self.ui
                    )
                )
                result = r or "Done."

            # ── File Processor ────────────────────────────────────────────────
            elif name == "file_processor":
                if not args.get("file_path") and self.ui.current_file:
                    args["file_path"] = self.ui.current_file
                r = await loop.run_in_executor(
                    None,
                    lambda: file_processor(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            # ── Computer Control ──────────────────────────────────────────────
            elif name == "computer_control":
                r = await loop.run_in_executor(
                    None,
                    lambda: computer_control(
                        parameters=args, player=self.ui
                    )
                )
                result = r or "Done."

            # ── Game Updater ──────────────────────────────────────────────────
            elif name == "game_updater":
                r = await loop.run_in_executor(
                    None,
                    lambda: game_updater(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            # ── Flight Finder ─────────────────────────────────────────────────
            elif name == "flight_finder":
                r = await loop.run_in_executor(
                    None,
                    lambda: flight_finder(
                        parameters=args, player=self.ui
                    )
                )
                result = r or "Done."

            # ── Smart Home ────────────────────────────────────────────────────
            elif name == "smart_home":
                r = await loop.run_in_executor(
                    None,
                    lambda: smart_home(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            # ── Number Tracer ─────────────────────────────────────────────────
            elif name == "number_tracer":
                r = await loop.run_in_executor(
                    None,
                    lambda: number_tracer(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            # ── Credential Manager ────────────────────────────────────────────
            elif name == "credential_manager":
                r = await loop.run_in_executor(
                    None,
                    lambda: credential_agent(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            # ── Email Agent ───────────────────────────────────────────────────
            elif name == "email_agent":
                r = await loop.run_in_executor(
                    None,
                    lambda: email_agent(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            # ── Social Agent ──────────────────────────────────────────────────
            elif name == "social_agent":
                r = await loop.run_in_executor(
                    None,
                    lambda: social_agent(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            # ── Daemon Control ────────────────────────────────────────────────
            elif name == "daemon_control":
                action = args.get("action", "status")
                daemon = get_daemon()
                if action == "status":
                    result = (
                        daemon.get_status()
                        if daemon else
                        "Daemon not running."
                    )
                elif action == "stop":
                    if daemon:
                        daemon.stop()
                        result = "Daemon stopped."
                    else:
                        result = "Daemon not running."
                elif action == "start":
                    if daemon and daemon.running:
                        result = "Daemon already running."
                    else:
                        new_daemon = JarvisDaemon(self)
                        new_daemon.start()
                        from core import daemon as daemon_module
                        daemon_module._daemon = new_daemon
                        result = "Daemon started."
                elif action == "restart":
                    if daemon:
                        daemon.stop()
                    new_daemon = JarvisDaemon(self)
                    new_daemon.start()
                    from core import daemon as daemon_module
                    daemon_module._daemon = new_daemon
                    result = "Daemon restarted."
                else:
                    result = f"Unknown daemon action: {action}"

            # ── Network Jammer ────────────────────────────────────────────────
            elif name == "network_jammer":
                r = await loop.run_in_executor(
                    None,
                    lambda: network_jammer(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            # ── Chart Analyst ─────────────────────────────────────────────────
            elif name == "chart_analyst":
                r = await loop.run_in_executor(
                    None,
                    lambda: chart_analyst(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            # ── Security Agent ────────────────────────────────────────────────
            elif name == "security_agent":
                target  = args.get("target", "")
                action  = args.get("action", "")
                timeout = int(
                    args.get("timeout", _smart_timeout(target))
                )
                args["timeout"] = timeout
                self.ui.write_log(
                    f"[SEC] {action} → {target or 'local'} "
                    f"(timeout: {timeout}s)"
                )
                r = await loop.run_in_executor(
                    None,
                    lambda: security_agent(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."
                if action == "nmap_full" and result.startswith("❌") and target:
                    self.ui.write_log(
                        "[SEC] nmap_full failed — trying fallback..."
                    )
                    for fallback_tool, fallback_opts in NMAP_FALLBACK_CHAIN[1:]:
                        fb             = dict(args)
                        fb["action"]   = fallback_tool
                        fb["options"]  = fallback_opts
                        fb["timeout"]  = _smart_timeout(target, base=180)
                        self.ui.write_log(
                            f"[SEC] Fallback: {fallback_tool}"
                        )
                        r2 = await loop.run_in_executor(
                            None,
                            lambda a=fb: security_agent(
                                parameters=a,
                                player=self.ui,
                                speak=self.speak
                            )
                        )
                        if r2 and not r2.startswith("❌"):
                            result = r2
                            break

            # ── Telegram Bot ──────────────────────────────────────────────────
            elif name == "telegram_bot":
                r = await loop.run_in_executor(
                    None,
                    lambda: telegram_agent(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            elif name == "terabox_backup":
                r = await loop.run_in_executor(
                    None,
                    lambda: terabox_backup_agent(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak,
                    )
                )
                result = r or "Done."

            # ── Social Login ──────────────────────────────────────────────────
            elif name == "social_login":
                r = await loop.run_in_executor(
                    None,
                    lambda: social_login_agent(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            # ── Trading Agent ─────────────────────────────────────────────────
            elif name == "trading_agent":
                r = await loop.run_in_executor(
                    None,
                    lambda: trading_agent(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            # ── Offensive Agent ───────────────────────────────────────────────
            elif name == "offensive_agent":
                r = await loop.run_in_executor(
                    None,
                    lambda: offensive_agent(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            # ── Phishing Agent ────────────────────────────────────────────────
            elif name == "phishing_agent":
                r = await loop.run_in_executor(
                    None,
                    lambda: run_phishing_agent(
                        args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            elif name == "metadata_sniper":
                r = await loop.run_in_executor(
                    None,
                    lambda: metadata_sniper(args, self.ui, self.speak)
                )
                result = r or "Done."

            # ── Shutdown JARVIS ───────────────────────────────────────────────
            elif name == "shutdown_jarvis":
                self.ui.write_log("SYS: Shutdown requested.")
                self.speak("Goodbye, sir.")
                import os as _os
                import time as _time
                import threading as _threading
                def _shutdown():
                    _time.sleep(2)
                    _os._exit(0)
                _threading.Thread(
                    target=_shutdown, daemon=True
                ).start()

            # ── Network Scan ──────────────────────────────────────────────────
            elif name == "network_scan":
                from core.network_scanner import show_scan_gui
                threading.Thread(
                    target=show_scan_gui,
                    kwargs={
                        "network": args.get("network"),
                        "speak":   self.speak,
                        "player":  self.ui,
                    },
                    daemon=True
                ).start()
                result = "Network scan started, sir."

            # ── Bluetooth Agent ───────────────────────────────────────────────
            elif name == "bluetooth_agent":
                r = await loop.run_in_executor(
                    None,
                    lambda: bluetooth_agent(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            # ── Dev Forge ─────────────────────────────────────────────────────
            elif name == "dev_forge":
                r = await loop.run_in_executor(
                    None,
                    lambda: dev_forge(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."

            elif name == "notes_agent":
                r = await loop.run_in_executor(
                    None,
                    lambda: notes_agent(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."

            elif name == "system_agent":
                r = await loop.run_in_executor(
                    None,
                    lambda: system_agent(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."

            elif name == "briefing_agent":
                r = await loop.run_in_executor(
                    None,
                    lambda: briefing_agent(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."

            elif name == "scope_agent":
                r = await loop.run_in_executor(
                    None,
                    lambda: scope_agent(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."

            elif name == "findings_agent":
                r = await loop.run_in_executor(
                    None,
                    lambda: findings_agent(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."

            elif name == "report_agent":
                r = await loop.run_in_executor(
                    None,
                    lambda: report_agent(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."

            elif name == "google_auth":
                r = await loop.run_in_executor(
                    None,
                    lambda: google_auth_agent(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."

            elif name == "gmail_agent":
                r = await loop.run_in_executor(
                    None,
                    lambda: gmail_agent(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."

            elif name == "calendar_agent":
                r = await loop.run_in_executor(
                    None,
                    lambda: calendar_agent(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."

            elif name == "docs_agent":
                r = await loop.run_in_executor(
                    None,
                    lambda: docs_agent(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."

            elif name == "drive_agent":
                r = await loop.run_in_executor(
                    None,
                    lambda: drive_agent(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."

            elif name == "notion_agent":
                r = await loop.run_in_executor(
                    None,
                    lambda: notion_agent(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."

            # ── Evolved Tools — dynamic dispatch ──────────────────────────────
            else:
                evo = get_evolution_engine(_get_api_key())
                if name in evo.loaded_tools:
                    self.ui.write_log(f"[EVO] Calling: {name}")
                    r = await loop.run_in_executor(
                        None,
                        lambda: evo.call_evolved_tool(
                            name, args,
                            player=self.ui,
                            speak=self.speak
                        )
                    )
                    result = r or "Done."
                else:
                    result = f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.speak_error(name, e)

        if not self.ui.muted:
            self.ui.set_state("LISTENING")

        result_str = _truncate_result(str(result), name)
        print(f"[JARVIS] 📤 {name} → {result_str[:80]}")

        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result_str}
        )

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send_realtime_input(media=msg)

    async def _listen_audio(self):
        print("[JARVIS] 🎤 Mic started")
        loop = asyncio.get_event_loop()

        def callback(indata, frames, time_info, status):
            with self._speaking_lock:
                jarvis_speaking = self._is_speaking
            if not jarvis_speaking and not self.ui.muted:
                data = indata.tobytes()
                try:
                    if self.out_queue and not self.out_queue.full():
                        loop.call_soon_threadsafe(
                            self.out_queue.put_nowait,
                            {"data": data, "mime_type": "audio/pcm"}
                        )
                except Exception:
                    pass

        try:
            with sd.InputStream(
                samplerate=SEND_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                callback=callback
            ):
                print("[JARVIS] 🎤 Mic stream open")
                while True:
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[JARVIS] ❌ Mic: {e}")
            raise

    async def _receive_audio(self):
        print("[JARVIS] 👂 Recv started")
        out_buf, in_buf = [], []
        try:
            while True:
                async for response in self.session.receive():
                    if response.data:
                        if (self._turn_done_event and
                                self._turn_done_event.is_set()):
                            self._turn_done_event.clear()
                        self.audio_in_queue.put_nowait(response.data)
                    if response.server_content:
                        sc = response.server_content
                        if (sc.output_transcription and
                                sc.output_transcription.text):
                            txt = _clean_transcript(
                                sc.output_transcription.text
                            )
                            if txt:
                                out_buf.append(txt)
                        if (sc.input_transcription and
                                sc.input_transcription.text):
                            txt = _clean_transcript(
                                sc.input_transcription.text
                            )
                            if txt:
                                in_buf.append(txt)
                        if sc.turn_complete:
                            if self._turn_done_event:
                                self._turn_done_event.set()
                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self.ui.write_log(f"You: {full_in}")
                            in_buf = []
                            full_out = " ".join(out_buf).strip()
                            if full_out:
                                self.ui.write_log(f"Jarvis: {full_out}")
                            out_buf = []
                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[JARVIS] 📞 {fc.name}")
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )
        except Exception as e:
            print(f"[JARVIS] ❌ Recv: {e}")
            traceback.print_exc()
            raise

    async def _play_audio(self):
        print("[JARVIS] 🔊 Play started")
        stream = sd.RawOutputStream(
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE
        )
        stream.start()
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        self.audio_in_queue.get(), timeout=0.1
                    )
                except asyncio.TimeoutError:
                    if (self._turn_done_event and
                            self._turn_done_event.is_set() and
                            self.audio_in_queue.empty()):
                        self.set_speaking(False)
                        self._turn_done_event.clear()
                    continue
                self.set_speaking(True)
                await asyncio.to_thread(stream.write, chunk)
        except Exception as e:
            print(f"[JARVIS] ❌ Play: {e}")
            raise
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()

    async def run(self):
        client = genai.Client(
            api_key=_get_api_key(),
            http_options={"api_version": "v1beta"}
        )
        while True:
            try:
                print("[JARVIS] 🔌 Connecting...")
                self.ui.set_state("THINKING")
                config = self._build_config()
                async with (
                    client.aio.live.connect(
                        model=LIVE_MODEL, config=config
                    ) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session          = session
                    self._loop            = asyncio.get_event_loop()
                    self.audio_in_queue   = asyncio.Queue()
                    self.out_queue        = asyncio.Queue(maxsize=20)
                    self._turn_done_event = asyncio.Event()
                    print("[JARVIS] ✅ Connected.")
                    self.ui.set_state("LISTENING")
                    self.ui.write_log("SYS: JARVIS online.")
                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())
            except Exception as e:
                print(f"[JARVIS] ⚠️ {e}")
                traceback.print_exc()
            self.set_speaking(False)
            self.ui.set_state("THINKING")
            print("[JARVIS] 🔄 Reconnecting in 3s...")
            await asyncio.sleep(3)


def main():
    ui = JarvisUI("face.png")

    def runner():
        if is_first_run():
            print("[JARVIS] 🆕 First run — launching setup wizard...")
            run_setup_wizard()

        try:
            from core.setup_wizard import (
                is_first_run_tracer,
                run_number_tracer_setup,
            )
            if is_first_run_tracer():
                print("[JARVIS] 🆕 Number Tracer first run — setup...")
                run_number_tracer_setup()
        except Exception as e:
            print(f"[JARVIS] Tracer setup skipped: {e}")

        try:
            if terabox_backup_autostart_enabled():
                print("[JARVIS] Starting Telegram-to-TeraBox backup...")
                print(terabox_backup_agent({"action": "start"}))
            else:
                print(
                    "[JARVIS] Telegram-to-TeraBox backup autostart disabled "
                    "by JARVIS_TERABOX_BACKUP_AUTOSTART."
                )
        except Exception as e:
            print(f"[JARVIS] TeraBox backup not started: {e}")

        try:
            tg_config = _load_tg_config()
            if tg_config.get("enabled") and tg_config.get("token"):
                print("[JARVIS] 📱 Starting Telegram bot...")
                start_telegram_bot(
                    token=tg_config["token"],
                    authorized_ids=tg_config.get("authorized_ids", []),
                    speak=None,
                    on_command=ui.on_text_command,
                    player=ui,
                )
        except Exception as e:
            print(f"[JARVIS] Telegram bot not started: {e}")

        try:
            evo = get_evolution_engine(_get_api_key())
            for tname, info in evo.loaded_tools.items():
                decl = info.get("declaration", {})
                if decl and decl.get("name") and \
                   decl["name"] not in [
                       t["name"] for t in TOOL_DECLARATIONS
                   ]:
                    TOOL_DECLARATIONS.append(decl)
                    print(
                        f"[JARVIS] 📋 Registered evolved tool: {tname}"
                    )
        except Exception as e:
            print(f"[JARVIS] Evolution engine skipped: {e}")

        ui.wait_for_api_key()
        jarvis = JarvisLive(ui)

        try:
            daemon = JarvisDaemon(jarvis)
            daemon.start()
            from core import daemon as daemon_module
            daemon_module._daemon = daemon
            print("[JARVIS] 🛡️ Daemon layer active")
        except Exception as e:
            print(f"[JARVIS] Daemon skipped: {e}")

        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\n🔴 Shutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()


if __name__ == "__main__":
    main()