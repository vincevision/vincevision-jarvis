import subprocess
import platform
import os
import time
import threading
import base64
from pathlib import Path
from datetime import datetime

try:
    from google import genai
    from google.genai import types as genai_types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

try:
    import groq as groq_lib
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

try:
    from core.credential_manager import get_credential
    CRED_AVAILABLE = True
except ImportError:
    CRED_AVAILABLE = False

OS = platform.system()

# ── Models ────────────────────────────────────────────────────────────────────
GROQ_VISION_MODEL  = "meta-llama/llama-4-scout-17b-16e-instruct"
GEMINI_VISION_MODEL = "gemini-1.5-flash"   # fallback — higher quota than 2.0

# ── Live monitor singleton ────────────────────────────────────────────────────
_live_monitor_thread: threading.Thread | None = None
_live_monitor_running = False


# ─────────────────────────────────────────────────────────────────────────────
# CREDENTIALS
# ─────────────────────────────────────────────────────────────────────────────

def _get_gemini_key() -> str:
    if CRED_AVAILABLE:
        key = get_credential("gemini", "api_key")
        if key:
            return key
    try:
        import json
        config_path = (
            Path(__file__).resolve().parent.parent / "config" / "api_keys.json"
        )
        with open(config_path) as f:
            return json.load(f).get("gemini_api_key", "")
    except Exception:
        return ""


def _get_groq_key() -> str:
    if CRED_AVAILABLE:
        key = get_credential("groq", "api_key")
        if key:
            return key
    try:
        import json
        config_path = (
            Path(__file__).resolve().parent.parent / "config" / "api_keys.json"
        )
        with open(config_path) as f:
            data = json.load(f)
            return data.get("groq_api_key", "") or data.get("groq_key", "")
    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# SCREENSHOT
# ─────────────────────────────────────────────────────────────────────────────

def _capture_screen() -> str | None:
    """Capture screen and return path to PNG file."""
    tmp_dir = (
        Path("/tmp")
        if OS != "Windows"
        else Path(os.environ.get("TEMP", "C:\\Temp"))
    )
    tmp_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = tmp_dir / f"chart_{int(time.time())}.png"

    try:
        if OS == "Linux":
            methods = [
                f"scrot '{screenshot_path}'",
                f"import -window root '{screenshot_path}'",
                f"gnome-screenshot -f '{screenshot_path}'",
                f"xwd -root -silent | convert xwd:- '{screenshot_path}'",
            ]
            for cmd in methods:
                try:
                    subprocess.run(
                        cmd, shell=True,
                        capture_output=True, timeout=10
                    )
                    if (
                        screenshot_path.exists()
                        and screenshot_path.stat().st_size > 1000
                    ):
                        break
                except Exception:
                    continue

        elif OS == "Darwin":
            subprocess.run(
                f"screencapture -x '{screenshot_path}'",
                shell=True, timeout=10
            )
        else:
            try:
                from PIL import ImageGrab
                img = ImageGrab.grab()
                img.save(str(screenshot_path))
            except ImportError:
                try:
                    import mss
                    with mss.mss() as sct:
                        sct.shot(output=str(screenshot_path))
                except ImportError:
                    return None

        if screenshot_path.exists() and screenshot_path.stat().st_size > 1000:
            return str(screenshot_path)
        return None

    except Exception as e:
        print(f"[CHART] Screenshot error: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# PROMPTS
# ─────────────────────────────────────────────────────────────────────────────

def _build_prompt(
    mode: str,
    user_context: str = "",
    symbol: str = "",
    timeframe: str = ""
) -> str:

    base = (
        "You are an elite professional trader with 20+ years experience. "
        "You specialize in ICT (Inner Circle Trader) and Smart Money Concepts (SMC). "
        "You understand: Order Blocks, Fair Value Gaps, Breaker Blocks, "
        "Liquidity sweeps, MSS, CHoCH, Premium/Discount arrays, Kill zones, "
        "and multi-timeframe analysis. "
        "Speak directly like a senior trader mentoring a junior. "
        "Be brutally honest. Keep responses concise but complete."
    )

    sym_tf = f"Symbol: {symbol or 'Unknown'} | Timeframe: {timeframe or 'Unknown'}"

    if mode == "analyze":
        return (
            f"{base}\n\nFULL CHART ANALYSIS\n{sym_tf}\n"
            f"User notes: {user_context or 'None'}\n\n"
            "Analyze and provide:\n"
            "1. Market Structure — trend, CHoCH/MSS\n"
            "2. Key Levels — OBs, FVGs, SR zones\n"
            "3. Liquidity — where are stops resting?\n"
            "4. Bias — Bullish/Bearish? Why?\n"
            "5. Trade Setup — Entry, SL, TP1, TP2\n"
            "6. Setup Quality — score 1-10\n"
            "7. Key levels to watch"
        )

    elif mode == "review":
        return (
            f"{base}\n\nREVIEW TRADER'S MARKED LEVELS\n{sym_tf}\n"
            f"Trader notes: {user_context or 'None'}\n\n"
            "Look at every marked level/zone/line on the chart.\n"
            "For each:\n"
            "- What type of level is it?\n"
            "- Verdict: CORRECT / WRONG / PARTIALLY CORRECT\n"
            "- Why correct or wrong?\n"
            "- If wrong, where should it actually be?\n\n"
            "End with overall quality score."
        )

    elif mode == "levels":
        return (
            f"{base}\n\nIDENTIFY ALL KEY LEVELS\n{sym_tf}\n\n"
            "Find and describe:\n"
            "1. Order Blocks (bullish/bearish)\n"
            "2. Fair Value Gaps\n"
            "3. Breaker Blocks\n"
            "4. Liquidity Pools (buy/sell stops)\n"
            "5. Key SR zones\n"
            "6. Premium/Discount location\n"
            "Format: Type | Price | Significance"
        )

    elif mode == "bias":
        return (
            f"{base}\n\nDETERMINE MARKET BIAS\n{sym_tf}\n\n"
            "Provide:\n"
            "1. HTF Bias — direction + reasoning\n"
            "2. LTF Bias — short term\n"
            "3. Conflicting signals\n"
            "4. Bias invalidation level\n"
            "5. Confidence: Weak/Moderate/Strong\n"
            "6. Next expected move"
        )

    elif mode == "entry":
        return (
            f"{base}\n\nFIND OPTIMAL ENTRY\n{sym_tf}\n"
            f"Trader plan: {user_context or 'Not specified'}\n\n"
            "Complete trade plan:\n"
            "1. Direction — Long or Short\n"
            "2. Entry Zone — exact price range\n"
            "3. Entry Trigger — confirmation needed\n"
            "4. Stop Loss — exact level + reason\n"
            "5. TP1 and TP2\n"
            "6. Risk/Reward ratio\n"
            "7. Invalidation level\n"
            "8. Best session to trade\n"
            "9. Quality score 1-10"
        )

    elif mode == "quick":
        return (
            f"{base}\n\nQUICK ANALYSIS (5 lines max)\n{sym_tf}\n\n"
            "- Bias: BULLISH/BEARISH/NEUTRAL\n"
            "- Key level: [price]\n"
            "- Next move: [brief]\n"
            "- Trade idea: Long/Short/No trade + reason\n"
            "- Risk: Low/Medium/High"
        )

    else:
        return (
            f"{base}\n\nANSWER TRADER QUESTION\n{sym_tf}\n"
            f"Question: {user_context}\n\n"
            "Answer directly and professionally."
        )


# ─────────────────────────────────────────────────────────────────────────────
# GROQ VISION ANALYSIS (Primary)
# ─────────────────────────────────────────────────────────────────────────────

def _analyze_with_groq(
    screenshot_path: str,
    prompt: str,
    player=None,
) -> str:
    """Use Groq's vision model for chart analysis."""
    if not GROQ_AVAILABLE:
        return None

    groq_key = _get_groq_key()
    if not groq_key:
        return None

    try:
        _log(player, "[CHART] 🟠 Using Groq vision...")

        with open(screenshot_path, "rb") as f:
            image_data = f.read()

        image_b64 = base64.b64encode(image_data).decode("utf-8")

        client = groq_lib.Groq(api_key=groq_key)

        response = client.chat.completions.create(
            model=GROQ_VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_b64}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=1500,
            temperature=0.3,
        )

        result = response.choices[0].message.content
        _log(player, "[CHART] ✅ Groq analysis complete")
        return result

    except Exception as e:
        err = str(e)
        _log(player, f"[CHART] Groq error: {err[:100]}")
        print(f"[CHART] Groq vision error: {err}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# GEMINI VISION ANALYSIS (Fallback)
# ─────────────────────────────────────────────────────────────────────────────

def _analyze_with_gemini(
    screenshot_path: str,
    prompt: str,
    player=None,
) -> str:
    """Use Gemini vision as fallback."""
    if not GENAI_AVAILABLE:
        return None

    api_key = _get_gemini_key()
    if not api_key:
        return None

    try:
        _log(player, f"[CHART] 🔵 Using Gemini vision ({GEMINI_VISION_MODEL})...")

        client = genai.Client(
            api_key=api_key,
            http_options={"api_version": "v1beta"}
        )

        with open(screenshot_path, "rb") as f:
            image_data = f.read()

        response = client.models.generate_content(
            model=GEMINI_VISION_MODEL,
            contents=[
                genai_types.Content(
                    role="user",
                    parts=[
                        genai_types.Part(text=prompt),
                        genai_types.Part(
                            inline_data=genai_types.Blob(
                                mime_type="image/png",
                                data=base64.b64encode(
                                    image_data
                                ).decode("utf-8")
                            )
                        )
                    ]
                )
            ],
            config=genai_types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=1500,
            )
        )

        result = response.text or "No analysis returned."
        _log(player, "[CHART] ✅ Gemini analysis complete")
        return result

    except Exception as e:
        err = str(e)
        _log(player, f"[CHART] Gemini error: {err[:100]}")
        print(f"[CHART] Gemini vision error: {err}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ANALYSIS ENGINE — tries Groq first, Gemini fallback
# ─────────────────────────────────────────────────────────────────────────────

def _analyze_chart(
    screenshot_path: str,
    mode: str,
    user_context: str = "",
    symbol: str = "",
    timeframe: str = "",
    player=None,
) -> str:
    """Try Groq first, fall back to Gemini."""

    prompt = _build_prompt(mode, user_context, symbol, timeframe)

    # Validate screenshot
    if not Path(screenshot_path).exists():
        return "Screenshot file not found."

    size = Path(screenshot_path).stat().st_size
    if size < 1000:
        return "Screenshot too small — capture may have failed."

    _log(player, f"[CHART] 📸 Image size: {size // 1024}KB")

    # Try Groq first (no quota issues on paid plan)
    result = _analyze_with_groq(screenshot_path, prompt, player)
    if result and len(result) > 50:
        return result

    # Fall back to Gemini
    _log(player, "[CHART] Groq failed or unavailable — trying Gemini...")
    result = _analyze_with_gemini(screenshot_path, prompt, player)
    if result and len(result) > 50:
        return result

    return (
        "Both AI providers failed. "
        "Check your Groq API key in credentials. "
        "Groq: https://console.groq.com/keys"
    )


# ─────────────────────────────────────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def _save_analysis(analysis: str, symbol: str = "", mode: str = "") -> str:
    save_dir = Path.home() / "JARVIS_Charts"
    save_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{symbol or 'chart'}_{mode}_{timestamp}.txt"
    filepath = save_dir / filename
    content = (
        f"JARVIS CHART ANALYSIS\n"
        f"{'='*60}\n"
        f"Symbol:    {symbol or 'Unknown'}\n"
        f"Mode:      {mode}\n"
        f"Time:      {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"{'='*60}\n\n"
        f"{analysis}\n"
    )
    filepath.write_text(content, encoding="utf-8")
    return str(filepath)


def _log(player, msg: str):
    if player:
        try:
            player.write_log(msg[:300])
        except Exception:
            pass


def _truncate_for_live(text: str, max_chars: int = 800) -> str:
    """
    Truncate result before returning to Gemini Live session.
    Large responses sent back through the websocket cause 1011 crashes.
    """
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [Full analysis logged to UI]"


# ─────────────────────────────────────────────────────────────────────────────
# MAIN AGENT FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def chart_analyst(parameters: dict, player=None, speak=None) -> str:

    action     = parameters.get("action", "analyze")
    symbol     = parameters.get("symbol", "")
    timeframe  = parameters.get("timeframe", "")
    context    = parameters.get("context", "")
    save       = parameters.get("save", False)
    interval   = int(parameters.get("interval", 30))
    screenshot = parameters.get("screenshot", "")

    global _live_monitor_thread, _live_monitor_running

    # ── STOP LIVE ─────────────────────────────────────────────────────────────
    if action == "stop_live":
        _live_monitor_running = False
        if speak:
            speak("Live chart monitoring stopped, sir.")
        return "Live monitoring stopped."

    # ── LIVE STATUS ───────────────────────────────────────────────────────────
    if action == "live_status":
        status = "active" if _live_monitor_running else "not running"
        return f"Live chart monitoring is {status}."

    # ── LIVE MONITORING ───────────────────────────────────────────────────────
    if action == "live":
        if _live_monitor_running:
            return "Live monitoring already running. Say stop live monitor to stop."

        if speak:
            speak(
                f"Starting live chart monitoring every {interval} seconds, sir."
            )

        _live_monitor_running = True

        def _live_loop():
            global _live_monitor_running
            _log(player, f"[CHART] 🔴 Live monitoring ({interval}s interval)")

            while _live_monitor_running:
                try:
                    path = _capture_screen()
                    if not path:
                        time.sleep(interval)
                        continue

                    analysis = _analyze_chart(
                        path, "quick", context, symbol, timeframe, player
                    )

                    # Log to UI
                    if player:
                        for line in analysis.split("\n"):
                            if line.strip():
                                _log(player, f"[CHART] {line.strip()}")

                    # Speak condensed
                    if (
                        speak and analysis
                        and "error" not in analysis.lower()
                        and "failed" not in analysis.lower()
                    ):
                        lines = [
                            l.strip() for l in analysis.split("\n")
                            if l.strip()
                        ]
                        spoken = " ".join(lines[:3])[:300]
                        if spoken:
                            speak(spoken)

                    try:
                        Path(path).unlink(missing_ok=True)
                    except Exception:
                        pass

                except Exception as e:
                    _log(player, f"[CHART] Live error: {e}")

                time.sleep(interval)

            _log(player, "[CHART] ⏹️ Live monitoring stopped")

        _live_monitor_thread = threading.Thread(
            target=_live_loop, daemon=True
        )
        _live_monitor_thread.start()
        return f"Live monitoring started — every {interval}s."

    # ── SINGLE ANALYSIS ───────────────────────────────────────────────────────
    mode_msgs = {
        "analyze": "Analyzing your chart now, sir. One moment.",
        "review":  "Reviewing your marked levels, sir. Stand by.",
        "levels":  "Identifying all key levels, sir.",
        "bias":    "Determining market bias, sir.",
        "entry":   "Finding optimal entry zones, sir.",
        "quick":   "Quick analysis incoming, sir.",
        "compare": "Analyzing your question about this chart, sir.",
    }

    if speak:
        speak(mode_msgs.get(action, "Analyzing chart, sir."))

    # Screenshot
    if screenshot and Path(screenshot).exists():
        path = screenshot
        _log(player, f"[CHART] Using provided screenshot: {path}")
    else:
        _log(player, "[CHART] 📸 Capturing screen...")
        path = _capture_screen()

    if not path:
        msg = (
            "Failed to capture screen. "
            "Run: sudo apt install scrot"
        )
        if speak:
            speak(msg)
        return msg

    _log(player, f"[CHART] 📸 Captured: {path}")

    # Analyze
    analysis = _analyze_chart(
        path, action, context, symbol, timeframe, player
    )

    # Log full analysis to UI
    if player:
        _log(player, "─" * 60)
        for line in analysis.split("\n"):
            if line.strip():
                _log(player, f"[CHART] {line.strip()}")
        _log(player, "─" * 60)

    # Save
    save_path = ""
    if save:
        try:
            save_path = _save_analysis(analysis, symbol, action)
            _log(player, f"[CHART] 💾 Saved: {save_path}")
        except Exception as e:
            _log(player, f"[CHART] Save error: {e}")

    # Speak summary
    if (
        speak and analysis
        and "error" not in analysis.lower()
        and "failed" not in analysis.lower()
    ):
        lines = [
            l.strip() for l in analysis.split("\n")
            if l.strip() and not l.strip().startswith("─")
        ]
        spoken = " ".join(lines[:6])[:500]
        if spoken:
            speak(spoken)

    # Cleanup
    try:
        Path(path).unlink(missing_ok=True)
    except Exception:
        pass

    result = analysis
    if save_path:
        result += f"\n\nSaved: {save_path}"

    # CRITICAL: Truncate before returning to Gemini Live
    return _truncate_for_live(result, max_chars=800)


# ── Declaration ───────────────────────────────────────────────────────────────
DECLARATION = {
    "name": "chart_analyst",
    "description": (
        "Professional AI chart analyst. Captures screen and analyzes "
        "charts like an elite ICT/SMC trader. Uses Groq vision (primary) "
        "with Gemini fallback."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action":     {"type": "STRING",  "description": "analyze | review | levels | bias | entry | quick | compare | live | stop_live | live_status"},
            "symbol":     {"type": "STRING",  "description": "e.g. XAUUSD, EURUSD, NAS100"},
            "timeframe":  {"type": "STRING",  "description": "e.g. 1H, 4H, 15M, 1D"},
            "context":    {"type": "STRING",  "description": "Your analysis or question"},
            "save":       {"type": "BOOLEAN", "description": "Save to file"},
            "interval":   {"type": "INTEGER", "description": "Live monitoring interval seconds"},
            "screenshot": {"type": "STRING",  "description": "Path to existing screenshot"},
        },
        "required": ["action"]
    }
}