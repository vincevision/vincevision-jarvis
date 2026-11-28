"""Offline tests for multi-channel alert delivery (core/alerts.py).

No network: every sender is monkeypatched. The promise is fan-out with
per-channel isolation — one broken channel never blocks the others.
"""

import json

import pytest

from core import alerts


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(alerts, "CONFIG_PATH", tmp_path / "alerts.json")
    monkeypatch.setattr(alerts, "HISTORY_PATH", tmp_path / "history.json")
    monkeypatch.setattr(alerts, "LOG_PATH", tmp_path / "logs" / "alerts.log")
    return tmp_path


@pytest.fixture
def sent(monkeypatch):
    """Capture deliveries without touching Gmail/Notion/Telegram."""
    calls = {"gmail": [], "notion": [], "telegram": []}
    monkeypatch.setattr(alerts, "_send_gmail",
                        lambda text, title, to: calls["gmail"].append((title, to)) or "sent")
    monkeypatch.setattr(alerts, "_send_notion",
                        lambda text, title, parent: calls["notion"].append((title, parent)) or "created")
    monkeypatch.setattr(alerts, "_send_telegram",
                        lambda text: calls["telegram"].append(text) or "sent")
    return calls


# ── config ─────────────────────────────────────────────────────────────────

def test_default_channels_are_local(store):
    assert alerts.load_config()["channels"] == ["file", "console"]


def test_load_config_from_file(store):
    alerts.CONFIG_PATH.write_text(json.dumps({"channels": ["gmail"], "email_to": "a@b.c"}),
                                  encoding="utf-8")
    cfg = alerts.load_config()
    assert cfg["channels"] == ["gmail"] and cfg["email_to"] == "a@b.c"


def test_load_config_corrupt(store):
    alerts.CONFIG_PATH.write_text("{bad", encoding="utf-8")
    assert alerts.load_config()["channels"] == ["file", "console"]


def test_load_config_non_list_channels(store):
    alerts.CONFIG_PATH.write_text(json.dumps({"channels": "gmail"}), encoding="utf-8")
    assert alerts.load_config()["channels"] == ["file", "console"]


def test_load_config_ignores_unknown(store):
    alerts.CONFIG_PATH.write_text(json.dumps({"evil": 1}), encoding="utf-8")
    assert "evil" not in alerts.load_config()


def test_save_config_roundtrip(store):
    assert alerts.save_config({"channels": ["telegram"]}) is True
    assert alerts.load_config()["channels"] == ["telegram"]


def test_save_config_bad_path(store):
    blocker = store / "f.txt"
    blocker.write_text("x", encoding="utf-8")
    assert alerts.save_config({}, path=blocker / "x.json") is False


# ── normalize_channels ─────────────────────────────────────────────────────

def test_normalize_list():
    assert alerts.normalize_channels(["gmail", "notion"]) == ["gmail", "notion"]


def test_normalize_csv():
    assert alerts.normalize_channels("gmail, telegram") == ["gmail", "telegram"]


def test_normalize_semicolons():
    assert alerts.normalize_channels("gmail;notion") == ["gmail", "notion"]


def test_normalize_aliases():
    assert alerts.normalize_channels("email,tg,log,ui") == [
        "gmail", "telegram", "file", "console"]
    assert alerts.normalize_channels("mail") == ["gmail"]


def test_normalize_dedupes():
    assert alerts.normalize_channels("gmail,gmail,email") == ["gmail"]


def test_normalize_drops_unknown():
    assert alerts.normalize_channels("gmail,myspace,fax") == ["gmail"]


def test_normalize_case_insensitive():
    assert alerts.normalize_channels("GMAIL,Telegram") == ["gmail", "telegram"]


def test_normalize_none_and_empty():
    assert alerts.normalize_channels(None) == []
    assert alerts.normalize_channels("") == []
    assert alerts.normalize_channels([]) == []


# ── levels + formatting ────────────────────────────────────────────────────

def test_level_ok_equal():
    assert alerts.level_ok("warning", "warning") is True


def test_level_ok_above():
    assert alerts.level_ok("critical", "info") is True


def test_level_ok_below():
    assert alerts.level_ok("info", "critical") is False


def test_level_ok_unknown_defaults_info():
    assert alerts.level_ok("weird", "warning") is False


def test_format_alert_contains_parts():
    text = alerts.format_alert("Price drop", "NBO→DXB $380", now=1_800_000_000)
    assert "Price drop" in text and "NBO→DXB $380" in text and "JARVIS" in text


@pytest.mark.parametrize("level,icon", [("info", "ℹ️"), ("warning", "⚠️"), ("critical", "🚨")])
def test_format_alert_icons(level, icon):
    assert icon in alerts.format_alert("t", "b", level)


def test_format_alert_unknown_level():
    assert "ℹ️" in alerts.format_alert("t", "b", "weird")


# ── notify fan-out ─────────────────────────────────────────────────────────

def test_notify_default_local_only(store, sent, capsys):
    res = alerts.notify("Test", "body")
    assert res["ok"] is True
    assert set(res["results"]) == {"file", "console"}
    assert alerts.LOG_PATH.exists()
    assert sent["gmail"] == []


def test_notify_file_content(store, sent):
    alerts.notify("Flight drop", "now $380")
    text = alerts.LOG_PATH.read_text(encoding="utf-8")
    assert "Flight drop" in text and "now $380" in text


def test_notify_explicit_channels(store, sent):
    res = alerts.notify("T", "b", channels=["gmail", "telegram"],
                        config={"channels": ["file"], "email_to": "a@b.c"})
    assert set(res["results"]) == {"gmail", "telegram"}
    assert sent["gmail"] and sent["telegram"]


def test_notify_config_channels(store, sent):
    alerts.notify("T", "b", config={"channels": ["telegram"]})
    assert sent["telegram"]


def test_notify_all_channels(store, sent):
    res = alerts.notify("T", "b", channels=list(alerts.CHANNELS),
                        config={"email_to": "a@b.c", "notion_parent": ""})
    assert set(res["results"]) == set(alerts.CHANNELS)
    assert res["ok"] is True


def test_notify_unknown_channel_reported(store, sent):
    res = alerts.notify("T", "b", channels=["gmail"], config={"email_to": "x@y.z"})
    assert "gmail" in res["results"]


def test_notify_channel_failure_isolated(store, sent, monkeypatch):
    def boom(text):
        raise RuntimeError("telegram down")
    monkeypatch.setattr(alerts, "_send_telegram", boom)
    res = alerts.notify("T", "b", channels=["telegram", "file"])
    assert res["results"]["telegram"].startswith("failed")
    assert "written" in res["results"]["file"]
    assert res["ok"] is True


def test_notify_all_fail_marks_not_ok(store, sent, monkeypatch):
    monkeypatch.setattr(alerts, "_send_telegram", lambda t: (_ for _ in ()).throw(OSError("x")))
    res = alerts.notify("T", "b", channels=["telegram"])
    assert res["ok"] is False


def test_notify_never_raises_on_sender_crash(store, monkeypatch):
    monkeypatch.setattr(alerts, "_send_file", lambda t: (_ for _ in ()).throw(RuntimeError("disk")))
    res = alerts.notify("T", "b", channels=["file"])
    assert isinstance(res, dict) and res["ok"] is False


def test_notify_respects_min_level(store, sent):
    res = alerts.notify("T", "b", level="info", config={"channels": ["file"], "min_level": "critical"})
    assert res["skipped"] is True and res["results"] == {}


def test_notify_critical_passes_min_level(store, sent):
    res = alerts.notify("T", "b", level="critical",
                        config={"channels": ["file"], "min_level": "warning"})
    assert res["skipped"] is False


def test_notify_empty_channels_falls_back_to_file(store, sent):
    res = alerts.notify("T", "b", channels=[], config={"channels": []})
    assert "file" in res["results"]


def test_notify_blank_title_default(store, sent):
    res = alerts.notify("", "")
    assert "JARVIS alert" in res["text"]


def test_notify_records_history(store, sent):
    alerts.notify("Price drop", "b")
    rows = alerts.load_history()
    assert len(rows) == 1 and rows[0]["title"] == "Price drop"


def test_history_bounded(store, sent, monkeypatch):
    monkeypatch.setattr(alerts, "MAX_HISTORY", 5)
    for i in range(20):
        alerts.notify(f"T{i}", "b", channels=["file"])
    rows = alerts.load_history()
    assert len(rows) == 5 and rows[-1]["title"] == "T19"


def test_load_history_corrupt(store):
    alerts.HISTORY_PATH.write_text("{bad", encoding="utf-8")
    assert alerts.load_history() == []


def test_load_history_non_list(store):
    alerts.HISTORY_PATH.write_text('{"a":1}', encoding="utf-8")
    assert alerts.load_history() == []


def test_load_history_missing(store):
    assert alerts.load_history() == []


def test_history_write_failure_is_soft(store, sent, monkeypatch):
    monkeypatch.setattr(alerts, "HISTORY_PATH", store / "f.txt" / "h.json")
    (store / "f.txt").write_text("x", encoding="utf-8")
    assert alerts.notify("T", "b")["ok"] is True


def test_notify_player_log(store, sent):
    lines = []

    class P:
        def write_log(self, t):
            lines.append(t)
    alerts.notify("T", "b", channels=["console"], player=P())
    assert lines


def test_notify_broken_player(store, sent):
    class P:
        def write_log(self, t):
            raise RuntimeError("ui down")
    assert alerts.notify("T", "b", channels=["console"], player=P())["ok"] is True


# ── real senders: skip paths + lazy imports ────────────────────────────────

def test_send_gmail_skips_without_recipient(store):
    assert "skipped" in alerts._send_gmail("text", "title", "")


def test_send_gmail_delegates(store, monkeypatch):
    import sys, types
    mod = types.ModuleType("actions.gmail_agent")
    calls = []
    mod.send_mail = lambda to, subject, body: calls.append((to, subject)) or "Email sent"
    monkeypatch.setitem(sys.modules, "actions.gmail_agent", mod)
    assert alerts._send_gmail("body", "Title", "a@b.c") == "Email sent"
    assert calls[0][0] == "a@b.c" and "[JARVIS] Title" in calls[0][1]


def test_send_notion_delegates(store, monkeypatch):
    import sys, types
    mod = types.ModuleType("actions.notion_agent")
    mod.create_page = lambda title, content, parent_id: "Page created"
    monkeypatch.setitem(sys.modules, "actions.notion_agent", mod)
    assert alerts._send_notion("body", "T", "") == "Page created"


def test_send_telegram_delegates(store, monkeypatch):
    import sys, types
    mod = types.ModuleType("actions.telegram_bot")
    mod.send_telegram_notification = lambda message: "sent"
    monkeypatch.setitem(sys.modules, "actions.telegram_bot", mod)
    assert alerts._send_telegram("hi") == "sent"


def test_send_console_no_player(store, capsys):
    assert alerts._send_console("hello") == "shown"
    assert "hello" in capsys.readouterr().out


def test_send_file_creates_dirs(store):
    alerts._send_file("x", path=store / "deep" / "nested" / "a.log")
    assert (store / "deep" / "nested" / "a.log").exists()


# ── channel_status ─────────────────────────────────────────────────────────

def test_channel_status_local_always_ready(store):
    st = alerts.channel_status({"channels": []})
    assert st["file"]["ready"] and st["console"]["ready"]


def test_channel_status_gmail_needs_recipient(store):
    assert alerts.channel_status({"email_to": ""})["gmail"]["ready"] is False
    assert alerts.channel_status({"email_to": "a@b.c"})["gmail"]["ready"] is True


def test_channel_status_notion_missing_module(store, monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "actions.notion_agent", None)
    assert alerts.channel_status({})["notion"]["ready"] is False


def test_channel_status_telegram_missing_module(store, monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "actions.telegram_bot", None)
    assert alerts.channel_status({})["telegram"]["ready"] is False


def test_channel_status_notion_configured(store, monkeypatch):
    import sys, types
    mod = types.ModuleType("actions.notion_agent")
    mod.is_configured = lambda: True
    monkeypatch.setitem(sys.modules, "actions.notion_agent", mod)
    assert alerts.channel_status({})["notion"]["ready"] is True


def test_channel_status_telegram_running(store, monkeypatch):
    import sys, types
    mod = types.ModuleType("actions.telegram_bot")
    mod.get_bot = lambda: object()
    monkeypatch.setitem(sys.modules, "actions.telegram_bot", mod)
    assert alerts.channel_status({})["telegram"]["ready"] is True


# ── alerts_control tool surface ────────────────────────────────────────────

def test_control_status(store, sent):
    out = alerts.alerts_control({"action": "status"})
    assert "Alerts" in out and "Enabled" in out


def test_control_send(store, sent):
    out = alerts.alerts_control({"action": "send", "title": "Hi", "body": "there",
                                 "channels": "file"})
    assert "delivery" in out and "file" in out


def test_control_test_alias(store, sent):
    assert "Test alert" in alerts.alerts_control({"action": "test", "channels": "file"})


def test_control_send_reports_failure(store, sent, monkeypatch):
    monkeypatch.setattr(alerts, "_send_telegram", lambda t: (_ for _ in ()).throw(OSError("x")))
    out = alerts.alerts_control({"action": "send", "channels": "telegram"})
    assert "❌" in out


def test_control_send_skipped(store, sent):
    alerts.save_config({"channels": ["file"], "min_level": "critical"})
    out = alerts.alerts_control({"action": "send", "channels": "file"})
    assert "not sent" in out


def test_control_history_empty(store):
    assert "No alerts" in alerts.alerts_control({"action": "history"})


def test_control_history_lists(store, sent):
    alerts.notify("Drop", "b", channels=["file"])
    out = alerts.alerts_control({"action": "history"})
    assert "Drop" in out and "ok" in out


def test_control_history_limit(store, sent):
    for i in range(6):
        alerts.notify(f"T{i}", "b", channels=["file"])
    out = alerts.alerts_control({"action": "history", "limit": 2})
    assert "T5" in out and "T0" not in out


def test_control_channels(store, sent):
    out = alerts.alerts_control({"action": "channels"})
    assert "gmail" in out and "telegram" in out


def test_control_enable(store, sent):
    out = alerts.alerts_control({"action": "enable", "channels": "telegram"})
    assert "telegram" in out
    assert "telegram" in alerts.load_config()["channels"]


def test_control_enable_keeps_existing(store, sent):
    alerts.alerts_control({"action": "enable", "channels": "telegram"})
    alerts.alerts_control({"action": "enable", "channels": "notion"})
    chans = alerts.load_config()["channels"]
    assert "telegram" in chans and "notion" in chans


def test_control_enable_no_channel(store):
    assert "Which channel" in alerts.alerts_control({"action": "enable"})


def test_control_enable_with_recipient(store, sent):
    alerts.alerts_control({"action": "enable", "channels": "gmail", "email_to": "a@b.c"})
    assert alerts.load_config()["email_to"] == "a@b.c"


def test_control_disable(store, sent):
    alerts.alerts_control({"action": "enable", "channels": "telegram,file"})
    out = alerts.alerts_control({"action": "disable", "channels": "telegram"})
    assert "telegram" not in alerts.load_config()["channels"]


def test_control_disable_no_channel(store):
    assert "Which channel" in alerts.alerts_control({"action": "disable"})


def test_control_recipient(store, sent):
    out = alerts.alerts_control({"action": "recipient", "email_to": "me@example.com"})
    assert "me@example.com" in out
    assert "gmail" in alerts.load_config()["channels"]


def test_control_recipient_missing(store):
    assert "email address" in alerts.alerts_control({"action": "recipient"})


def test_control_level(store):
    assert "warning" in alerts.alerts_control({"action": "level", "min_level": "warning"})
    assert alerts.load_config()["min_level"] == "warning"


def test_control_level_invalid(store):
    assert "min_level must be" in alerts.alerts_control({"action": "level", "min_level": "loud"})


def test_control_none_params(store, sent):
    assert isinstance(alerts.alerts_control(None), str)


def test_control_unknown_action(store, sent):
    assert "Actions:" in alerts.alerts_control({"action": "zzz"})


def test_control_is_crash_proof(store, monkeypatch):
    monkeypatch.setattr(alerts, "load_config", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("cfg")))
    out = alerts.alerts_control({"action": "status"})
    assert "problem" in out and "session is still running" in out
