"""Offline tests for the show-me layer (core/visible.py).

The promise: work happens ON SCREEN and every step is narrated, and a broken
UI/speaker can never take a tool down.
"""

import json

import pytest

from core import visible as vis


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    path = tmp_path / "visible.json"
    monkeypatch.setattr(vis, "CONFIG_PATH", path)
    monkeypatch.delenv("JARVIS_SHOW_ME", raising=False)
    monkeypatch.delenv("JARVIS_PACE", raising=False)
    return path


class Player:
    def __init__(self, explode=False):
        self.lines = []
        self.explode = explode

    def write_log(self, text):
        if self.explode:
            raise RuntimeError("UI down")
        self.lines.append(text)


@pytest.fixture
def fast(monkeypatch):
    """No real sleeping in tests."""
    slept = []
    monkeypatch.setattr(vis.time, "sleep", lambda s: slept.append(s))
    return slept


# ── config ─────────────────────────────────────────────────────────────────

def test_defaults_show_me_on(cfg):
    c = vis.load_config()
    assert c["show_me"] is True and c["keep_open"] is True


def test_defaults_speak_steps_off(cfg):
    assert vis.load_config()["speak_steps"] is False


def test_load_from_file(cfg):
    cfg.write_text(json.dumps({"show_me": False, "pace": 0.5}), encoding="utf-8")
    c = vis.load_config()
    assert c["show_me"] is False and c["pace"] == 0.5


def test_load_ignores_unknown_keys(cfg):
    cfg.write_text(json.dumps({"evil": 1, "pace": 2}), encoding="utf-8")
    assert "evil" not in vis.load_config()


def test_load_corrupt_file(cfg):
    cfg.write_text("{not json", encoding="utf-8")
    assert vis.load_config()["show_me"] is True


def test_load_non_dict(cfg):
    cfg.write_text("[1,2]", encoding="utf-8")
    assert isinstance(vis.load_config(), dict)


def test_load_missing_file(cfg):
    assert vis.load_config() == vis.DEFAULTS


def test_env_show_me_off(cfg, monkeypatch):
    monkeypatch.setenv("JARVIS_SHOW_ME", "0")
    assert vis.load_config()["show_me"] is False


@pytest.mark.parametrize("val", ["1", "true", "YES", "on"])
def test_env_show_me_on(cfg, monkeypatch, val):
    monkeypatch.setenv("JARVIS_SHOW_ME", val)
    assert vis.load_config()["show_me"] is True


def test_env_overrides_file(cfg, monkeypatch):
    cfg.write_text(json.dumps({"show_me": True}), encoding="utf-8")
    monkeypatch.setenv("JARVIS_SHOW_ME", "0")
    assert vis.load_config()["show_me"] is False


def test_env_pace(cfg, monkeypatch):
    monkeypatch.setenv("JARVIS_PACE", "3.5")
    assert vis.load_config()["pace"] == 3.5


def test_env_pace_bad_value(cfg, monkeypatch):
    monkeypatch.setenv("JARVIS_PACE", "soon")
    assert vis.load_config()["pace"] == vis.DEFAULTS["pace"]


def test_pace_clamped_high(cfg, monkeypatch):
    monkeypatch.setenv("JARVIS_PACE", "900")
    assert vis.load_config()["pace"] == 10.0


def test_pace_clamped_negative(cfg, monkeypatch):
    monkeypatch.setenv("JARVIS_PACE", "-5")
    assert vis.load_config()["pace"] == 0.0


def test_pace_non_numeric_in_file(cfg):
    cfg.write_text(json.dumps({"pace": "fast"}), encoding="utf-8")
    assert vis.load_config()["pace"] == vis.DEFAULTS["pace"]


# ── visible() browser params ───────────────────────────────────────────────

def test_visible_forces_headless_false(cfg):
    out = vis.visible({"action": "go_to", "url": "https://x.com", "headless": True})
    assert out["headless"] is False


def test_visible_keeps_window_open(cfg):
    assert vis.visible({"action": "go_to"})["keep_open"] is True


def test_visible_preserves_other_params(cfg):
    out = vis.visible({"action": "get_text", "limit": 40000})
    assert out["limit"] == 40000 and out["action"] == "get_text"


def test_visible_does_not_mutate_input(cfg):
    src = {"action": "go_to", "headless": True}
    vis.visible(src)
    assert src["headless"] is True


def test_visible_none_params(cfg):
    assert vis.visible(None)["headless"] is False


def test_visible_explicit_config_off(cfg):
    out = vis.visible({"headless": True}, config={"show_me": False})
    assert out["headless"] is True


def test_visible_off_still_defaults_headless_false(cfg):
    assert vis.visible({}, config={"show_me": False})["headless"] is False


def test_visible_keep_open_off(cfg):
    out = vis.visible({}, config={"show_me": True, "keep_open": False})
    assert "keep_open" not in out


# ── Narrator ───────────────────────────────────────────────────────────────

def test_narrator_records_steps(cfg, fast):
    n = vis.Narrator(config={"show_me": True, "pace": 0})
    n.doing("Opening kayak")
    n.done("Found 3 fares")
    assert len(n.steps) == 2 and "Opening kayak" in n.steps[0]


def test_narrator_writes_to_player(cfg, fast):
    p = Player()
    n = vis.Narrator(p, config={"show_me": True, "pace": 0})
    n.doing("Reading prices")
    assert p.lines and "Reading prices" in p.lines[0]


def test_narrator_prefix(cfg, fast):
    p = Player()
    vis.Narrator(p, prefix="Hotels", config={"show_me": True, "pace": 0}).doing("x")
    assert p.lines[0].startswith("[Hotels]")


def test_narrator_symbols(cfg, fast):
    n = vis.Narrator(config={"show_me": True, "pace": 0})
    n.doing("a"); n.done("b"); n.warn("c"); n.info("d")
    assert n.steps[0].startswith("▸") and n.steps[1].startswith("✓")
    assert n.steps[2].startswith("⚠️")


def test_narrator_disabled_still_records(cfg, fast):
    p = Player()
    n = vis.Narrator(p, config={"show_me": False})
    n.doing("quiet work")
    assert n.steps and p.lines == []


def test_narrator_speaks_only_when_chatty(cfg, fast):
    said = []
    n = vis.Narrator(speak=said.append, config={"show_me": True, "speak_steps": True, "pace": 0})
    n.doing("Opening site")
    assert said == ["Opening site"]


def test_narrator_silent_by_default(cfg, fast):
    said = []
    vis.Narrator(speak=said.append, config={"show_me": True, "pace": 0}).doing("x")
    assert said == []


def test_narrator_done_can_skip_speech(cfg, fast):
    said = []
    n = vis.Narrator(speak=said.append,
                     config={"show_me": True, "speak_steps": True, "pace": 0})
    n.done("x", speak_it=False)
    assert said == []


def test_narrator_survives_broken_player(cfg, fast):
    n = vis.Narrator(Player(explode=True), config={"show_me": True, "pace": 0})
    n.doing("x")           # must not raise
    assert n.steps


def test_narrator_survives_broken_speaker(cfg, fast):
    def bad(_):
        raise OSError("no audio")
    n = vis.Narrator(speak=bad, config={"show_me": True, "speak_steps": True, "pace": 0})
    n.doing("x")
    assert n.steps


def test_narrator_pace_pauses(cfg, fast):
    n = vis.Narrator(config={"show_me": True, "pace": 1.5})
    n.doing("x")
    assert fast == [1.5]


def test_narrator_zero_pace_no_sleep(cfg, fast):
    vis.Narrator(config={"show_me": True, "pace": 0}).doing("x")
    assert fast == []


def test_narrator_disabled_no_sleep(cfg, fast):
    vis.Narrator(config={"show_me": False, "pace": 5}).doing("x")
    assert fast == []


def test_narrator_custom_sleeper(cfg):
    slept = []
    n = vis.Narrator(config={"show_me": True, "pace": 2}, sleeper=slept.append)
    n.doing("x")
    assert slept == [2]


def test_narrator_pause_bad_value(cfg, fast):
    n = vis.Narrator(config={"show_me": True, "pace": 0})
    n.pause("soon")        # must not raise
    assert fast == []


def test_narrator_pause_negative(cfg, fast):
    n = vis.Narrator(config={"show_me": True, "pace": 0})
    n.pause(-3)
    assert fast == []


def test_narrator_survives_broken_sleeper(cfg):
    def bad(_):
        raise RuntimeError("clock gone")
    n = vis.Narrator(config={"show_me": True, "pace": 1}, sleeper=bad)
    n.doing("x")
    assert n.steps


def test_narrator_transcript(cfg, fast):
    n = vis.Narrator(config={"show_me": True, "pace": 0})
    n.doing("one"); n.done("two")
    assert "one" in n.transcript() and "\n" in n.transcript()


def test_narrator_enabled_property(cfg):
    assert vis.Narrator(config={"show_me": True}).enabled is True
    assert vis.Narrator(config={"show_me": False}).enabled is False


def test_narrator_no_args_uses_config(cfg, fast):
    n = vis.Narrator()
    assert n.enabled is True


# ── open_visible ───────────────────────────────────────────────────────────

def test_open_visible_calls_browser(cfg, fast):
    calls = []

    def browser(params, player=None):
        calls.append(params)
        return "opened"
    out = vis.open_visible("https://kayak.com", label="Kayak", browser=browser)
    assert out == "opened"
    assert calls[0]["url"] == "https://kayak.com" and calls[0]["headless"] is False


def test_open_visible_narrates(cfg, fast):
    n = vis.Narrator(config={"show_me": True, "pace": 0})
    vis.open_visible("https://x.com", narrator=n, label="X", browser=lambda p, player=None: "ok")
    assert any("Opening X" in s for s in n.steps)
    assert any("Opened X" in s for s in n.steps)


def test_open_visible_failure_is_soft(cfg, fast):
    def boom(params, player=None):
        raise RuntimeError("browser missing")
    n = vis.Narrator(config={"show_me": True, "pace": 0})
    out = vis.open_visible("https://x.com", narrator=n, browser=boom)
    assert "Could not open" in out
    assert any("⚠️" in s for s in n.steps)


def test_open_visible_none_result(cfg, fast):
    out = vis.open_visible("https://x.com", browser=lambda p, player=None: None)
    assert out == "opened"


# ── visible_control tool ───────────────────────────────────────────────────

def test_control_status(cfg):
    out = vis.visible_control({"action": "status"})
    assert "Show-me: ON" in out and "Pace" in out


def test_control_on(cfg, monkeypatch):
    assert "ON" in vis.visible_control({"action": "on"})
    assert vis.load_config()["show_me"] is True


def test_control_off(cfg):
    assert "OFF" in vis.visible_control({"action": "off"})
    assert vis.load_config()["show_me"] is False


def test_control_pace(cfg):
    assert "2.0s" in vis.visible_control({"action": "pace", "seconds": 2})
    assert vis.load_config()["pace"] == 2.0


def test_control_pace_clamped(cfg):
    vis.visible_control({"action": "pace", "seconds": 999})
    assert vis.load_config()["pace"] == 10.0


def test_control_pace_bad(cfg):
    assert "number" in vis.visible_control({"action": "pace", "seconds": "fast"})


def test_control_chatty_toggles(cfg):
    first = vis.visible_control({"action": "chatty"})
    assert "on" in first
    assert json.loads(cfg.read_text(encoding="utf-8"))["speak_steps"] is True
    vis.visible_control({"action": "chatty"})
    assert json.loads(cfg.read_text(encoding="utf-8"))["speak_steps"] is False


def test_control_chatty_preserves_other_keys(cfg):
    cfg.write_text(json.dumps({"pace": 0.4}), encoding="utf-8")
    vis.visible_control({"action": "chatty"})
    assert json.loads(cfg.read_text(encoding="utf-8"))["pace"] == 0.4


def test_control_none_params(cfg):
    assert isinstance(vis.visible_control(None), str)


def test_control_unknown_action(cfg):
    assert "Actions:" in vis.visible_control({"action": "zzz"})
