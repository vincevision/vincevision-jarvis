"""
Crash-proofing for JARVIS tools
───────────────────────────────
Every tool dispatcher should return a *string*, never raise. This module
provides the safety net that makes that guarantee cheap:

    @safe_tool("hotel_manager")
    def hotel_manager(parameters, player=None, speak=None) -> str:
        ...

If anything inside raises, the user gets a readable message, the traceback is
appended to logs/crashes.log (bounded), and the session keeps running.

Design rules
────────────
* Never swallow KeyboardInterrupt / SystemExit — those are deliberate stops.
* Never let the safety net itself raise: logging and callbacks are wrapped.
* Missing optional dependencies become a clear install hint, not a traceback.
* `guard()` is the inline form for one risky call.
"""

from __future__ import annotations

import functools
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

CRASH_LOG = Path("logs") / "crashes.log"
MAX_LOG_BYTES = 512 * 1024
MAX_ENTRIES = 200

_MISSING_HINTS = {
    "playwright": "pip install playwright && playwright install chromium",
    "selenium": "pip install selenium webdriver-manager",
    "sounddevice": "pip install sounddevice",
    "google": "pip install google-genai google-api-python-client google-auth-oauthlib",
    "requests": "pip install requests",
    "pyautogui": "pip install pyautogui",
    "send2trash": "pip install send2trash",
}


def _base_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def install_hint(exc: BaseException) -> str:
    """Turn a ModuleNotFoundError into an actionable install command."""
    name = getattr(exc, "name", "") or ""
    root = name.split(".")[0].lower()
    if isinstance(exc, ModuleNotFoundError) and root in _MISSING_HINTS:
        return f" Missing dependency '{root}'. Install it with: {_MISSING_HINTS[root]}"
    return ""


def log_crash(label: str, exc: BaseException, path=None) -> None:
    """Append a bounded crash record. Never raises."""
    try:
        p = Path(path) if path else _base_dir() / CRASH_LOG
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and p.stat().st_size > MAX_LOG_BYTES:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines(True)
            p.write_text("".join(lines[-MAX_ENTRIES:]), encoding="utf-8")
        stamp = datetime.now().isoformat(timespec="seconds")
        entry = (f"\n[{stamp}] {label}: {type(exc).__name__}: {exc}\n"
                 + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        with open(p, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception:
        pass


def friendly(label: str, exc: BaseException) -> str:
    """A short, honest, user-facing failure message."""
    kind = type(exc).__name__
    detail = str(exc).strip() or kind
    if len(detail) > 220:
        detail = detail[:220] + "…"
    hint = install_hint(exc)
    return (f"⚠️ {label} hit a problem ({kind}: {detail})."
            f"{hint} Nothing was lost — the session is still running. "
            f"Details in {CRASH_LOG}.")


def guard(fn, *args, default=None, label: str = "operation", **kwargs):
    """Call fn safely; return `default` on any Exception.

    A missing callback (None) is a no-op, not a crash — optional UI/speech
    hooks are absent in headless runs and must not pollute the crash log.
    """
    if not callable(fn):
        return default
    try:
        return fn(*args, **kwargs)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        log_crash(label, exc)
        return default


def safe_tool(label: str | None = None, notify: bool = True):
    """Decorator: a tool dispatcher that can never raise.

    The wrapped function keeps its signature. `player` and `speak` are used
    (if present) to surface the failure in the UI and by voice.
    """
    def decorator(fn):
        name = label or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                result = fn(*args, **kwargs)
                if result is None:
                    return "Done."
                return result if isinstance(result, str) else str(result)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                log_crash(name, exc)
                message = friendly(name, exc)
                if notify:
                    player = kwargs.get("player")
                    if player is None and len(args) > 1:
                        player = args[1]
                    guard(getattr(player, "write_log", None), message, label=f"{name}.log")
                    speak = kwargs.get("speak")
                    if speak is None and len(args) > 2:
                        speak = args[2]
                    guard(speak, f"Sir, {name} hit a problem but I've kept running.",
                          label=f"{name}.speak")
                return message
        return wrapper
    return decorator


def read_crashes(limit: int = 10, path=None) -> list[str]:
    """Recent crash headers (no full tracebacks) for the dashboard."""
    try:
        p = Path(path) if path else _base_dir() / CRASH_LOG
        if not p.exists():
            return []
        heads = [ln.strip() for ln in p.read_text(encoding="utf-8", errors="replace").splitlines()
                 if ln.startswith("[")]
        return heads[-max(1, int(limit)):]
    except Exception:
        return []


def crash_stats(path=None) -> dict:
    try:
        p = Path(path) if path else _base_dir() / CRASH_LOG
        if not p.exists():
            return {"total": 0, "recent": [], "log": str(CRASH_LOG)}
        heads = [ln.strip() for ln in p.read_text(encoding="utf-8", errors="replace").splitlines()
                 if ln.startswith("[")]
        return {"total": len(heads), "recent": heads[-5:], "log": str(CRASH_LOG)}
    except Exception:
        return {"total": 0, "recent": [], "log": str(CRASH_LOG)}


def health_control(parameters: dict, player=None, speak=None) -> str:
    """Tool surface: 'how healthy is JARVIS?' — crash log + dependency check."""
    params = parameters or {}
    action = str(params.get("action", "status")).lower().strip()
    if action in ("crashes", "log"):
        rows = read_crashes(int(params.get("limit", 10)))
        if not rows:
            return "✅ No crashes recorded."
        return f"⚠️ {len(rows)} recent issue(s):\n" + "\n".join(f"  {r}" for r in rows)
    if action == "clear":
        try:
            p = _base_dir() / CRASH_LOG
            if p.exists():
                p.write_text("", encoding="utf-8")
            return "🧹 Crash log cleared."
        except Exception as exc:
            return f"Could not clear the log: {exc}"
    if action == "deps":
        import importlib.util
        lines = []
        for mod, hint in _MISSING_HINTS.items():
            try:
                found = importlib.util.find_spec(mod) is not None
            except Exception:
                found = False
            lines.append(f"  {'✅' if found else '❌'} {mod}" + ("" if found else f" — {hint}"))
        return "Dependencies:\n" + "\n".join(lines)
    stats = crash_stats()
    if stats["total"] == 0:
        return "✅ JARVIS is healthy — no crashes recorded."
    return (f"⚠️ {stats['total']} issue(s) logged (all contained, session kept running).\n"
            + "\n".join(f"  {r}" for r in stats["recent"]))


# Apply the net to this module's own dispatcher too.
health_control = safe_tool("health_control")(health_control)
