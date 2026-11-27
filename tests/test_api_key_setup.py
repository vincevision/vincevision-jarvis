"""Offline tests for the first-run API-key popup (core/api_key_setup.py).

No display and no tkinter required: we test the pure helpers, the GUI
availability pre-check, the fallback decision, and the integration with
credential_manager.run_setup_wizard. The Tk dialog itself is only built when
a real display exists, so it is exercised via fakes here.
"""

import builtins
import getpass

import pytest

import core.api_key_setup as aks
import core.credential_manager as cm


# ── validate_keys ───────────────────────────────────────────────────────────

def test_validate_empty_gemini():
    ok, msg = aks.validate_keys("")
    assert not ok and "required" in msg


def test_validate_placeholder_gemini():
    ok, msg = aks.validate_keys("YOUR_GEMINI_API_KEY_HERE")
    assert not ok and "placeholder" in msg


def test_validate_short_gemini():
    ok, msg = aks.validate_keys("short")
    assert not ok and "short" in msg


def test_validate_valid_gemini():
    ok, msg = aks.validate_keys("fake-gemini-key-0123456789abcdef")
    assert ok and msg == ""


def test_validate_groq_optional():
    ok, _ = aks.validate_keys("fake-gemini-key-0123456789abcdef", "")
    assert ok


def test_validate_short_groq_rejected():
    ok, msg = aks.validate_keys("fake-gemini-key-0123456789abcdef", "tiny")
    assert not ok and "Groq" in msg


def test_validate_strips_whitespace():
    ok, _ = aks.validate_keys("  fake-gemini-key-0123456789abcdef  ")
    assert ok


# ── save_api_keys ───────────────────────────────────────────────────────────

def _capture_cm(monkeypatch):
    saved, json_updates, marked = {}, {}, []

    def save_cred(service, key, value):
        saved.setdefault(service, {})[key] = value

    monkeypatch.setattr(cm, "save_credential", save_cred)
    monkeypatch.setattr(cm, "_update_api_keys_json",
                        lambda k, v: json_updates.__setitem__(k, v))
    monkeypatch.setattr(cm, "mark_setup_complete", lambda: marked.append(True))
    return saved, json_updates, marked


def test_save_both_keys(monkeypatch):
    saved, json_updates, marked = _capture_cm(monkeypatch)
    out = aks.save_api_keys("fake-gemini-key-0123456789abcdef", "fake-groq-key-0123456789abcdef")
    assert saved["gemini"]["api_key"] == "fake-gemini-key-0123456789abcdef"
    assert saved["groq"]["api_key"] == "fake-groq-key-0123456789abcdef"
    assert json_updates["gemini_api_key"] and json_updates["groq_api_key"]
    assert marked == [True]
    assert "Gemini" in out and "Groq" in out


def test_save_gemini_only(monkeypatch):
    saved, json_updates, marked = _capture_cm(monkeypatch)
    out = aks.save_api_keys("fake-gemini-key-0123456789abcdef", "")
    assert "gemini" in saved and "groq" not in saved
    assert "groq_api_key" not in json_updates
    assert marked == [True]


def test_save_skip_marks_complete(monkeypatch):
    saved, json_updates, marked = _capture_cm(monkeypatch)
    out = aks.save_api_keys("", "")
    assert saved == {} and json_updates == {}
    assert marked == [True]
    assert "skipped" in out.lower()


def test_save_strips_whitespace(monkeypatch):
    saved, _, _ = _capture_cm(monkeypatch)
    aks.save_api_keys("  fake-gemini-key-0123456789abcdef  ", "  ")
    assert saved["gemini"]["api_key"] == "fake-gemini-key-0123456789abcdef"


# ── GUI availability ────────────────────────────────────────────────────────

def test_gui_available_respects_no_gui_env(monkeypatch):
    monkeypatch.setenv("JARVIS_NO_GUI", "1")
    assert aks.gui_available() is False


def test_display_present_linux_no_display(monkeypatch):
    monkeypatch.setattr(aks.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert aks._display_present() is False


def test_display_present_linux_with_display(monkeypatch):
    monkeypatch.setattr(aks.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":0")
    assert aks._display_present() is True


def test_display_present_non_linux(monkeypatch):
    monkeypatch.setattr(aks.sys, "platform", "win32")
    assert aks._display_present() is True


def test_gui_available_false_without_display(monkeypatch):
    monkeypatch.delenv("JARVIS_NO_GUI", raising=False)
    monkeypatch.setattr(aks, "_display_present", lambda: False)
    assert aks.gui_available() is False


# ── run_gui_setup orchestration ─────────────────────────────────────────────

def test_run_gui_setup_none_when_unavailable(monkeypatch):
    monkeypatch.setattr(aks, "gui_available", lambda: False)
    assert aks.run_gui_setup() is None


def test_run_gui_setup_returns_dialog_result(monkeypatch):
    monkeypatch.setattr(aks, "gui_available", lambda: True)

    class FakeDialog:
        result = "Setup complete (fake)"
        def run(self):
            pass

    monkeypatch.setattr(aks, "_SetupDialog", FakeDialog)
    assert aks.run_gui_setup() == "Setup complete (fake)"


def test_run_gui_setup_none_on_dialog_error(monkeypatch):
    monkeypatch.setattr(aks, "gui_available", lambda: True)

    class BoomDialog:
        def __init__(self):
            raise RuntimeError("no display")

    monkeypatch.setattr(aks, "_SetupDialog", BoomDialog)
    assert aks.run_gui_setup() is None


# ── integration with run_setup_wizard ───────────────────────────────────────

def test_run_setup_wizard_uses_gui(monkeypatch):
    monkeypatch.setattr(aks, "run_gui_setup", lambda: "Setup complete (GUI)")
    out = cm.run_setup_wizard()
    assert "GUI" in out


def test_run_setup_wizard_falls_back_to_terminal(monkeypatch):
    # GUI unavailable → terminal path; simulate empty keys + skip email
    monkeypatch.setattr(aks, "run_gui_setup", lambda: None)
    monkeypatch.setattr(getpass, "getpass", lambda *a, **k: "")
    monkeypatch.setattr(builtins, "input", lambda *a, **k: "n")
    marked = []
    monkeypatch.setattr(cm, "mark_setup_complete", lambda: marked.append(True))
    out = cm.run_setup_wizard()
    assert "Setup complete" in out
    assert marked == [True]


def test_module_imports_without_tkinter():
    # The module must be importable in a stdlib-only env (CI). If tkinter were
    # imported at module top, this import would already have failed.
    assert hasattr(aks, "run_gui_setup")
    assert hasattr(aks, "save_api_keys")
