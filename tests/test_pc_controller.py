"""Offline tests for pc_controller and the daemon default-off helper.

All delegation is monkeypatched — no browser, pyautogui, shell, or file
side effects. Verifies routing, the visible-research flow + fallback,
trash-by-default delete, the confirm gate for destructive ops, and that the
daemon is OFF by default.
"""

import pytest

import actions.pc_controller as pc
import core.daemon as daemon_mod


# ── pure helpers ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cmd", [
    "rm -rf /", "rm -rf /*", "rm -rf ~", "rm -fr /",
    "mkfs.ext4 /dev/sda", "dd if=/dev/zero of=/dev/sda",
    "shutdown now", "reboot", "format c:", "del /f /s /q C:\\",
])
def test_dangerous_commands_detected(cmd):
    assert pc._is_dangerous_command(cmd) is True


@pytest.mark.parametrize("cmd", [
    "ls -la", "echo hello", "python script.py", "rm -rf /home/user/project",
    "git status", "cat file.txt",
])
def test_safe_commands_not_flagged(cmd):
    assert pc._is_dangerous_command(cmd) is False


def test_confirmed():
    assert pc._confirmed({"confirm": "true"})
    assert pc._confirmed({"confirm": "yes"})
    assert pc._confirmed({"confirm": True})
    assert not pc._confirmed({})
    assert not pc._confirmed({"confirm": "false"})


def test_app_command_linux():
    assert pc._app_command("terminal", "linux") == ["x-terminal-emulator"]
    assert pc._app_command("calculator", "linux") == ["gnome-calculator"]


def test_app_command_windows():
    assert pc._app_command("calculator", "windows") == ["calc"]
    assert pc._app_command("notepad", "Windows") == ["notepad"]


def test_app_command_mac():
    assert pc._app_command("terminal", "darwin") == ["open", "-a", "Terminal"]


def test_app_command_unknown():
    assert pc._app_command("nonexistent_xyz", "linux") is None


def test_normalize_url():
    assert pc._normalize_url("") == "https://www.google.com"
    assert pc._normalize_url("example.com") == "https://example.com"
    assert pc._normalize_url("http://x.com") == "http://x.com"


# ── routing / delegation ────────────────────────────────────────────────────

def test_status():
    assert "PC controller" in pc.pc_controller({"action": "status"})


def test_unknown_action():
    assert "Unknown" in pc.pc_controller({"action": "bogus"})


def test_open_browser(monkeypatch):
    calls = []
    monkeypatch.setattr(pc, "_call_browser",
                        lambda p, player=None: calls.append(p) or "opened")
    pc.pc_controller({"action": "open_browser", "url": "example.com"})
    assert calls[0]["url"] == "https://example.com"
    assert calls[0]["headless"] is False


def test_research_visible_typing(monkeypatch):
    calls = []

    def fake_browser(p, player=None):
        calls.append(p)
        return "Typed into textarea" if p["action"] == "type" else "ok"

    monkeypatch.setattr(pc, "_call_browser", fake_browser)
    monkeypatch.setattr(pc, "_call_search", lambda p, player=None: "Summary of results")
    out = pc.pc_controller({"action": "research", "query": "python asyncio"})
    assert "Summary of results" in out
    assert any(c["action"] == "type" for c in calls)
    assert any(c["action"] == "press" for c in calls)


def test_research_fallback_to_search(monkeypatch):
    def fake_browser(p, player=None):
        if p["action"] == "type":
            return "Type failed: no element"
        if p["action"] == "search":
            return "Searched visible"
        return "ok"

    monkeypatch.setattr(pc, "_call_browser", fake_browser)
    monkeypatch.setattr(pc, "_call_search", lambda p, player=None: "Summary")
    out = pc.pc_controller({"action": "research", "query": "x"})
    assert "Summary" in out and "Searched visible" in out


def test_research_empty_query():
    assert "What should I research" in pc.pc_controller({"action": "research"})


def test_type_delegates(monkeypatch):
    calls = []
    monkeypatch.setattr(pc, "_call_computer",
                        lambda p, player=None: calls.append(p) or "typed")
    pc.pc_controller({"action": "type", "text": "hello"})
    assert calls[0]["action"] == "type" and calls[0]["text"] == "hello"


def test_close_browser(monkeypatch):
    calls = []
    monkeypatch.setattr(pc, "_call_browser",
                        lambda p, player=None: calls.append(p) or "closed")
    pc.pc_controller({"action": "close_browser"})
    assert calls[0]["action"] == "close_all"


# ── delete safety ───────────────────────────────────────────────────────────

def test_delete_default_trash(monkeypatch):
    calls = []
    monkeypatch.setattr(pc, "_call_files",
                        lambda p, player=None: calls.append(p) or "Deleted file.txt")
    out = pc.pc_controller({"action": "delete", "path": "desktop", "name": "file.txt"})
    assert "trash" in out.lower()
    assert calls[0]["action"] == "delete"


def test_delete_requires_target():
    assert "What should I delete" in pc.pc_controller({"action": "delete"})


def test_delete_permanent_needs_confirm():
    out = pc.pc_controller({"action": "delete", "path": "desktop",
                            "name": "f.txt", "permanent": "true"})
    assert "confirm=true" in out


def test_delete_permanent_confirmed(tmp_path, monkeypatch):
    import actions.file_controller as fc
    victim = tmp_path / "file.txt"
    victim.write_text("x")
    monkeypatch.setattr(fc, "_resolve_path", lambda p: tmp_path)
    monkeypatch.setattr(fc, "_is_safe_path", lambda t: True)
    out = pc.pc_controller({"action": "delete", "path": str(tmp_path),
                            "name": "file.txt", "permanent": "true", "confirm": "true"})
    assert "Permanently deleted" in out
    assert not victim.exists()


def test_delete_permanent_unsafe_path(tmp_path, monkeypatch):
    import actions.file_controller as fc
    monkeypatch.setattr(fc, "_resolve_path", lambda p: tmp_path)
    monkeypatch.setattr(fc, "_is_safe_path", lambda t: False)
    out = pc.pc_controller({"action": "delete", "path": str(tmp_path),
                            "name": "f.txt", "permanent": "true", "confirm": "true"})
    assert "Access denied" in out


# ── run safety ──────────────────────────────────────────────────────────────

def test_run_safe(monkeypatch):
    calls = []
    monkeypatch.setattr(pc, "_call_computer",
                        lambda p, player=None: calls.append(p) or "output")
    out = pc.pc_controller({"action": "run", "command": "ls -la"})
    assert out == "output"
    assert calls[0]["action"] == "run_command"


def test_run_dangerous_blocked():
    out = pc.pc_controller({"action": "run", "command": "rm -rf /"})
    assert "destructive" in out.lower()


def test_run_dangerous_confirmed(monkeypatch):
    monkeypatch.setattr(pc, "_call_computer", lambda p, player=None: "ran")
    out = pc.pc_controller({"action": "run", "command": "shutdown now", "confirm": "true"})
    assert out == "ran"


def test_run_empty():
    assert "Which command" in pc.pc_controller({"action": "run"})


# ── open_app ────────────────────────────────────────────────────────────────

def test_open_app_known(monkeypatch):
    monkeypatch.setattr(pc.subprocess, "Popen", lambda *a, **k: None)
    out = pc.pc_controller({"action": "open_app", "name": "terminal"})
    assert "Opened" in out


def test_open_app_unknown():
    out = pc.pc_controller({"action": "open_app", "name": "nonexistent_xyz"})
    assert "don't know" in out


# ── daemon default-off ──────────────────────────────────────────────────────

def test_daemon_default_off(monkeypatch, tmp_path):
    monkeypatch.delenv("JARVIS_DAEMON", raising=False)
    assert daemon_mod.daemon_enabled_by_default(config_path=tmp_path / "nope.json") is False


def test_daemon_env_on(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_DAEMON", "1")
    assert daemon_mod.daemon_enabled_by_default(config_path=tmp_path / "nope.json") is True


def test_daemon_env_off(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_DAEMON", "0")
    assert daemon_mod.daemon_enabled_by_default(config_path=tmp_path / "nope.json") is False


def test_daemon_config_on(monkeypatch, tmp_path):
    monkeypatch.delenv("JARVIS_DAEMON", raising=False)
    cfg = tmp_path / "daemon.json"
    cfg.write_text('{"enabled": true}')
    assert daemon_mod.daemon_enabled_by_default(config_path=cfg) is True


def test_daemon_config_off(monkeypatch, tmp_path):
    monkeypatch.delenv("JARVIS_DAEMON", raising=False)
    cfg = tmp_path / "daemon.json"
    cfg.write_text('{"enabled": false}')
    assert daemon_mod.daemon_enabled_by_default(config_path=cfg) is False


def test_daemon_env_overrides_config(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_DAEMON", "0")
    cfg = tmp_path / "daemon.json"
    cfg.write_text('{"enabled": true}')
    assert daemon_mod.daemon_enabled_by_default(config_path=cfg) is False
