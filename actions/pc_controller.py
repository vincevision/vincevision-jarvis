"""
pc_controller.py — VINCEVISION unified PC control
──────────────────────────────────────────────────
One high-level agent that drives the whole computer by orchestrating the
existing low-level agents (no duplicated automation logic):

  * open_browser / research  → browser_control (visible window) + web_search
  * type / click / hotkey …  → computer_control (pyautogui, visible typing)
  * delete / files           → file_controller (trash-based, safe-path guarded)
  * open_app                 → cross-platform app launcher
  * run                      → shell command (catastrophic commands need confirm)

Safety:
  * Delete goes to the RECYCLE BIN / trash by default (recoverable). Permanent
    delete requires confirm=true and stays inside the user's safe directories.
  * Catastrophic shell commands (rm -rf /, mkfs, shutdown, …) are blocked
    unless confirm=true.
  * pyautogui FAILSAFE stays on (slam mouse to a corner to abort).

Actions: open_browser, research, type, smart_type, click, hotkey, press,
         scroll, screenshot, delete, open_app, run, close_browser, status
"""

import platform
import re
import shutil
import subprocess
from pathlib import Path


# ── Delegates (lazy imports; monkeypatchable in tests) ──────────────────────

def _call_browser(params: dict, player=None) -> str:
    from actions.browser_control import browser_control
    return browser_control(parameters=params, player=player)


def _call_computer(params: dict, player=None) -> str:
    from actions.computer_control import computer_control
    return computer_control(parameters=params, player=player)


def _call_files(params: dict, player=None) -> str:
    from actions.file_controller import file_controller
    return file_controller(parameters=params, player=player)


def _call_search(params: dict, player=None) -> str:
    from actions.web_search import web_search
    return web_search(parameters=params, player=player)


# ── Pure helpers (testable without side effects) ────────────────────────────

_DANGEROUS_PATTERNS = [
    r"\brm\s+-[rf]{1,2}\s+/(?:\s|$)",      # rm -rf /
    r"\brm\s+-[rf]{1,2}\s+/\*",             # rm -rf /*
    r"\brm\s+-[rf]{1,2}\s+~",               # rm -rf ~
    r"\brm\s+-[rf]{1,2}\s+\$home",          # rm -rf $HOME
    r"\bmkfs(?:\.\w+)?\b",                  # mkfs.*
    r"\bdd\b[^\n]*\bof=/dev/",              # dd of=/dev/…
    r":\(\)\s*\{[^}]*\}\s*;\s*:",           # fork bomb
    r"\b(?:shutdown|reboot|halt|poweroff)\b",
    r"\bformat\s+[a-z]:",                   # format C:
    r"\bdel\s+/[a-z]*[fsq]",                # del /f /s /q
    r"\brd\s+/s",                           # rd /s
    r">\s*/dev/sd[a-z]",                    # overwrite disk
    r"\bchmod\s+-r\s+777\s+/(?:\s|$)",
]


def _is_dangerous_command(command: str) -> bool:
    c = (command or "").lower()
    return any(re.search(p, c) for p in _DANGEROUS_PATTERNS)


def _confirmed(params: dict) -> bool:
    return str(params.get("confirm", "")).lower() in ("1", "true", "yes", "on")


def _app_command(name: str, os_name: str = ""):
    """Return an argv list to launch a common app, or None if unknown."""
    os_name = (os_name or platform.system()).lower()
    if os_name == "darwin":
        os_name = "mac"
    elif os_name.startswith("win"):
        os_name = "windows"
    else:
        os_name = "linux"
    n = (name or "").lower().strip()
    home = str(Path.home())

    apps = {
        "linux": {
            "terminal": ["x-terminal-emulator"],
            "files": ["xdg-open", home], "file manager": ["xdg-open", home],
            "calculator": ["gnome-calculator"],
            "editor": ["gedit"], "text editor": ["gedit"],
            "settings": ["gnome-control-center"],
            "browser": ["xdg-open", "https://www.google.com"],
            "system monitor": ["gnome-system-monitor"],
        },
        "windows": {
            "terminal": ["cmd"], "cmd": ["cmd"], "powershell": ["powershell"],
            "files": ["explorer"], "file manager": ["explorer"],
            "calculator": ["calc"],
            "editor": ["notepad"], "notepad": ["notepad"],
            "browser": ["cmd", "/c", "start", "https://www.google.com"],
            "settings": ["cmd", "/c", "start", "ms-settings:"],
            "task manager": ["taskmgr"],
        },
        "mac": {
            "terminal": ["open", "-a", "Terminal"],
            "files": ["open", home], "finder": ["open", home],
            "calculator": ["open", "-a", "Calculator"],
            "editor": ["open", "-a", "TextEdit"],
            "browser": ["open", "https://www.google.com"],
            "settings": ["open", "-a", "System Settings"],
            "activity monitor": ["open", "-a", "Activity Monitor"],
        },
    }
    return apps.get(os_name, {}).get(n)


def _normalize_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return "https://www.google.com"
    if not re.match(r"^[a-z]+://", u):
        u = "https://" + u
    return u


# ── High-level operations ───────────────────────────────────────────────────

def _open_browser(url: str, player=None) -> str:
    return _call_browser({"action": "go_to", "url": _normalize_url(url),
                          "headless": False}, player)


def _research(query: str, engine: str, player=None, speak=None) -> str:
    if not query:
        return "What should I research, sir?"
    if speak:
        speak(f"Researching {query}, sir.")
    # Open a visible browser and type the query so the user can watch.
    try:
        _call_browser({"action": "go_to", "url": "https://www.google.com",
                       "headless": False}, player)
        typed = _call_browser({"action": "type", "selector": "textarea[name=q]",
                               "text": query}, player)
        if "fail" in str(typed).lower():
            raise RuntimeError(typed)
        _call_browser({"action": "press", "key": "Enter"}, player)
        browser_msg = "Opened the browser and typed your search."
    except Exception:
        try:
            browser_msg = _call_browser({"action": "search", "query": query,
                                         "engine": engine, "headless": False}, player)
        except Exception as e:
            browser_msg = f"(browser view unavailable: {e})"
    try:
        summary = _call_search({"query": query}, player)
    except Exception as e:
        summary = f"Search failed: {e}"
    return f"🔎 Research: {query}\n\n{summary}\n\n[Browser: {browser_msg}]"


def _delete(path: str, name: str, permanent: bool, params: dict, player=None) -> str:
    if not path and not name:
        return "What should I delete, sir? Provide a path or name."
    if permanent:
        if not _confirmed(params):
            return ("Permanent delete can't be undone. Re-send with confirm=true "
                    "to proceed, or omit permanent to move it to the trash instead.")
        from actions.file_controller import _resolve_path, _is_safe_path
        base = _resolve_path(path or "desktop")
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Not found: {target.name}"
        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            return f"🗑️ Permanently deleted {target.name}."
        except Exception as e:
            return f"Could not delete: {e}"
    # Default: recoverable trash delete via file_controller.
    out = _call_files({"action": "delete", "path": path or "desktop", "name": name}, player)
    return f"{out} (moved to trash — recoverable)"


def _launch_app(name: str) -> str:
    cmd = _app_command(name)
    if not cmd:
        return (f"I don't know how to open '{name}'. Try: browser, terminal, "
                "files, calculator, editor, settings, system monitor.")
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"✅ Opened {name}."
    except Exception as e:
        return f"Couldn't open {name}: {e}"


def _run(command: str, params: dict, player=None) -> str:
    if not command:
        return "Which command should I run, sir?"
    if _is_dangerous_command(command) and not _confirmed(params):
        return (f"⛔ That looks destructive ({command[:60]}). "
                "Re-send with confirm=true if you really mean it.")
    return _call_computer({"action": "run_command", "command": command,
                           "timeout": int(params.get("timeout", 30))}, player)


# ── Main dispatch ───────────────────────────────────────────────────────────

def pc_controller(parameters: dict, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).lower().strip()

    try:
        if action in ("status", "help"):
            return ("🖥️ PC controller ready. I can: open_browser, research, type, "
                    "smart_type, click, hotkey, press, scroll, screenshot, delete "
                    "(trash by default), open_app, run, close_browser. "
                    "Destructive actions need confirm=true.")

        if action in ("open_browser", "browser", "open"):
            return _open_browser(params.get("url", ""), player)

        if action in ("research", "search", "look_up"):
            return _research(params.get("query", ""), params.get("engine", "google"),
                             player, speak)

        if action in ("type", "smart_type"):
            return _call_computer({"action": action, "text": params.get("text", ""),
                                   "interval": float(params.get("interval", 0.05))}, player)

        if action in ("click", "double_click", "right_click", "move", "drag",
                      "hotkey", "press", "scroll", "screenshot", "copy", "paste",
                      "clear_field", "focus_window"):
            return _call_computer({**params, "action": action}, player)

        if action in ("delete", "remove", "trash"):
            permanent = str(params.get("permanent", "")).lower() in ("1", "true", "yes")
            return _delete(params.get("path", ""), params.get("name", ""),
                           permanent, params, player)

        if action in ("open_app", "launch", "app"):
            return _launch_app(params.get("name") or params.get("app", ""))

        if action in ("run", "command", "shell"):
            return _run(params.get("command") or params.get("text", ""), params, player)

        if action in ("close_browser", "close_all"):
            return _call_browser({"action": "close_all"}, player)

        return (f"Unknown pc_controller action '{action}'. Try: open_browser, "
                "research, type, delete, open_app, run, status.")
    except Exception as e:
        return f"pc_controller '{action}' failed: {e}"
