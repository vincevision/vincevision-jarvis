"""
"Show me" layer — make JARVIS work in front of you, not behind your back
────────────────────────────────────────────────────────────────────────
Two things:

1. **Narrator** — every step is written to the UI log, printed to the console,
   and optionally spoken, so you can follow along:
       ▸ Opening kayak.com…
       ▸ Reading prices…
       ✓ Found 12 offers

2. **Visible browser defaults** — `visible()` forces headless=False and keeps
   the window open, so searches happen on screen where you can watch them.

Visibility is ON by default. Turn it down with:
    config/visible.json -> {"show_me": false, "speak_steps": false, "pace": 0}
    or env JARVIS_SHOW_ME=0 / JARVIS_PACE=0

Nothing here raises: a broken UI callback can never take down a tool.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

CONFIG_PATH = Path("config") / "visible.json"

DEFAULTS = {
    "show_me": True,        # narrate + force a visible browser
    "speak_steps": False,   # speak each step (chatty; off by default)
    "pace": 1.2,            # seconds to pause so a human can follow
    "keep_open": True,      # leave the browser window open after a search
}


def load_config(path=None) -> dict:
    cfg = dict(DEFAULTS)
    p = Path(path) if path else CONFIG_PATH
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update({k: v for k, v in data.items() if k in cfg})
    except Exception:
        pass
    env = os.environ.get("JARVIS_SHOW_ME")
    if env is not None:
        cfg["show_me"] = env.strip().lower() in ("1", "true", "yes", "on")
    pace = os.environ.get("JARVIS_PACE")
    if pace is not None:
        try:
            cfg["pace"] = max(0.0, float(pace))
        except (TypeError, ValueError):
            pass
    try:
        cfg["pace"] = max(0.0, min(float(cfg["pace"]), 10.0))
    except (TypeError, ValueError):
        cfg["pace"] = DEFAULTS["pace"]
    return cfg


def visible(params: dict | None = None, config: dict | None = None) -> dict:
    """Force browser params into watchable mode (never headless)."""
    cfg = config or load_config()
    out = dict(params or {})
    if cfg.get("show_me", True):
        out["headless"] = False
        if cfg.get("keep_open", True):
            out.setdefault("keep_open", True)
    else:
        out.setdefault("headless", False)
    return out


class Narrator:
    """Step-by-step commentary that cannot crash the caller."""

    def __init__(self, player=None, speak=None, config: dict | None = None,
                 prefix: str = "", echo: bool = True, sleeper=None):
        self.player = player
        self.speak = speak
        self.config = config or load_config()
        self.prefix = prefix or ""
        self.echo = echo
        self._sleep = sleeper or time.sleep
        self.steps: list[str] = []

    @property
    def enabled(self) -> bool:
        return bool(self.config.get("show_me", True))

    def _emit(self, text: str, speak_it: bool = False):
        self.steps.append(text)
        if not self.enabled:
            return
        tag = f"[{self.prefix}] " if self.prefix else ""
        line = f"{tag}{text}"
        # Speech gets the words only — never the ▸ / ✓ / ⚠️ glyphs.
        spoken = text.lstrip("▸✓️ ").strip()
        if self.echo:
            try:
                print(line)
            except Exception:
                pass
        writer = getattr(self.player, "write_log", None)
        if callable(writer):
            try:
                writer(line)
            except Exception:
                pass
        if speak_it and self.config.get("speak_steps") and callable(self.speak):
            try:
                self.speak(spoken or text)
            except Exception:
                pass

    def doing(self, text: str, speak_it: bool = True):
        self._emit(f"▸ {text}", speak_it)
        self.pause()

    def done(self, text: str, speak_it: bool = True):
        self._emit(f"✓ {text}", speak_it)

    def warn(self, text: str):
        self._emit(f"⚠️ {text}", True)

    def info(self, text: str):
        self._emit(f"  {text}")

    def pause(self, seconds: float | None = None):
        if not self.enabled:
            return
        delay = self.config.get("pace", 1.2) if seconds is None else seconds
        try:
            delay = max(0.0, float(delay))
        except (TypeError, ValueError):
            return
        if delay:
            try:
                self._sleep(delay)
            except Exception:
                pass

    def transcript(self) -> str:
        return "\n".join(self.steps)


def open_visible(url: str, narrator: Narrator | None = None, label: str = "",
                 browser=None) -> str:
    """Open a URL in a visible browser, narrating it. Returns a status string."""
    n = narrator or Narrator()
    n.doing(f"Opening {label or url}")
    call = browser
    if call is None:
        def call(params, player=None):
            from actions.browser_control import browser_control
            return browser_control(parameters=params, player=player)
    try:
        result = call(visible({"action": "go_to", "url": url}), n.player)
        n.done(f"Opened {label or url}")
        return str(result or "opened")
    except Exception as exc:
        n.warn(f"Could not open {label or url}: {str(exc)[:90]}")
        return f"Could not open {label or url}: {exc}"


def visible_control(parameters: dict, player=None, speak=None) -> str:
    """Tool surface: toggle watchability at runtime."""
    params = parameters or {}
    action = str(params.get("action", "status")).lower().strip()
    cfg = load_config()
    if action in ("on", "enable", "show"):
        os.environ["JARVIS_SHOW_ME"] = "1"
        return ("👁️ Show-me mode ON — I'll open sites in a visible browser and "
                "narrate every step.")
    if action in ("off", "disable", "quiet"):
        os.environ["JARVIS_SHOW_ME"] = "0"
        return "👁️ Show-me mode OFF — I'll work quietly in the background."
    if action == "pace":
        try:
            os.environ["JARVIS_PACE"] = str(max(0.0, min(float(params.get("seconds", 1.2)), 10.0)))
        except (TypeError, ValueError):
            return "pace needs a number of seconds (0–10)."
        return f"⏱️ Step pacing set to {os.environ['JARVIS_PACE']}s."
    if action == "chatty":
        path = Path(CONFIG_PATH)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
            data["speak_steps"] = not bool(data.get("speak_steps"))
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return f"🗣️ Speaking each step: {'on' if data['speak_steps'] else 'off'}."
        except Exception as exc:
            return f"Could not change that setting: {exc}"
    return (f"👁️ Show-me: {'ON' if cfg['show_me'] else 'OFF'}\n"
            f"  Pace: {cfg['pace']}s per step\n"
            f"  Speak steps: {'on' if cfg['speak_steps'] else 'off'}\n"
            f"  Keep browser open: {'yes' if cfg['keep_open'] else 'no'}\n"
            "Actions: on, off, pace (seconds), chatty, status")
