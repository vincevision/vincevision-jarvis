"""Offline tests for wake-word matching and barge-in gating (no microphone)."""

import json

import pytest

from core import wake_word as ww


# ── normalization ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("  Hey,   JARVIS!  ", "hey jarvis"),
    ("Open the browser.", "open the browser"),
    ("", ""), (None, ""),
])
def test_normalize(raw, expected):
    assert ww.normalize(raw) == expected


# ── wake-word matching ──────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "jarvis", "Jarvis open chrome", "hey jarvis", "HEY JARVIS!",
    "ok jarvis what time is it", "yo jarvis", "hi jarvis",
    "um jarvis open the browser",
])
def test_matches_positive(text):
    assert ww.matches_wake_word(text) is True


@pytest.mark.parametrize("text", [
    "jervis open chrome", "jarviz status", "hey jarviss",
])
def test_matches_fuzzy(text):
    assert ww.matches_wake_word(text) is True


@pytest.mark.parametrize("text", [
    "", None, "open the browser", "what is the weather",
    "the jarvis project is nice",       # not at the start
])
def test_matches_negative(text):
    assert ww.matches_wake_word(text) is False


def test_custom_aliases():
    assert ww.matches_wake_word("computer do it", aliases=["computer"]) is True
    assert ww.matches_wake_word("jarvis do it", aliases=["computer"]) is False


def test_strict_threshold_rejects_fuzzy():
    assert ww.matches_wake_word("jervis", threshold=0.99) is False


# ── command extraction ──────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("hey jarvis open the browser", "open the browser"),
    ("jarvis what time is it", "what time is it"),
    ("ok jarvis", ""),
    ("um hey jarvis delete the file", "delete the file"),
    ("open the browser", "open the browser"),
    ("", ""),
])
def test_extract_command(text, expected):
    assert ww.extract_command(text) == expected


def test_extract_longest_alias_wins():
    assert ww.extract_command("hey jarvis run", aliases=["jarvis", "hey jarvis"]) == "run"


# ── RMS ─────────────────────────────────────────────────────────────────────

def test_compute_rms():
    assert ww.compute_rms([1, -1, 1, -1]) == pytest.approx(1.0)
    assert ww.compute_rms([0, 0]) == 0.0
    assert ww.compute_rms([]) == 0.0
    assert ww.compute_rms(None) == 0.0


def test_compute_rms_skips_bad_values():
    assert ww.compute_rms([1, "bad", -1]) == pytest.approx(1.0)


# ── barge-in gate ───────────────────────────────────────────────────────────

def test_gate_idle_never_interrupts():
    g = ww.BargeInGate()
    assert g.feed(0.9, 100.0) is False


def test_gate_echo_guard():
    g = ww.BargeInGate(echo_guard_ms=400)
    g.start_speaking(100.0)
    assert g.feed(0.9, 100.1) is False
    assert g.feed(0.9, 100.2) is False


def test_gate_requires_sustained_speech():
    g = ww.BargeInGate(min_speech_ms=250)
    g.start_speaking(100.0)
    assert g.feed(0.5, 101.0) is False      # streak starts
    assert g.feed(0.5, 101.1) is False      # only 100 ms
    assert g.feed(0.5, 101.3) is True       # 300 ms


def test_gate_quiet_resets_streak():
    g = ww.BargeInGate(min_speech_ms=250)
    g.start_speaking(100.0)
    g.feed(0.5, 101.0)
    g.feed(0.0, 101.2)                      # silence breaks it
    assert g.feed(0.5, 101.3) is False      # new streak
    assert g.feed(0.5, 101.6) is True


def test_gate_below_threshold():
    g = ww.BargeInGate(threshold=0.05)
    g.start_speaking(100.0)
    assert g.feed(0.01, 101.0) is False
    assert g.feed(0.01, 102.0) is False


def test_gate_cooldown():
    g = ww.BargeInGate(min_speech_ms=100, cooldown_s=2.0)
    g.start_speaking(100.0)
    g.feed(0.5, 101.0)
    assert g.feed(0.5, 101.2) is True
    g.feed(0.5, 102.0)
    assert g.feed(0.5, 102.2) is False      # inside cooldown
    # Sustained speech fires as soon as the cooldown expires.
    assert g.feed(0.5, 104.0) is True


def test_gate_stop_speaking():
    g = ww.BargeInGate(min_speech_ms=100)
    g.start_speaking(100.0)
    g.feed(0.5, 101.0)
    g.stop_speaking(101.1)
    assert g.feed(0.5, 102.0) is False


def test_gate_counts_and_reset():
    g = ww.BargeInGate(min_speech_ms=100, cooldown_s=0)
    g.start_speaking(100.0)
    g.feed(0.5, 101.0)
    g.feed(0.5, 101.2)
    assert g.interrupts == 1
    g.reset()
    assert g.interrupts == 0 and g.speaking is False


# ── config ─────────────────────────────────────────────────────────────────

def test_load_config_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_WAKE_WORD", raising=False)
    cfg = ww.load_config(tmp_path / "none.json")
    assert cfg["enabled"] is True and cfg["barge_in"] is True
    assert "jarvis" in cfg["aliases"]


def test_load_config_file(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_WAKE_WORD", raising=False)
    p = tmp_path / "w.json"
    p.write_text(json.dumps({"aliases": ["computer"], "rms_threshold": 0.1}))
    cfg = ww.load_config(p)
    assert cfg["aliases"] == ["computer"] and cfg["rms_threshold"] == 0.1


def test_load_config_env_override(tmp_path, monkeypatch):
    p = tmp_path / "w.json"
    p.write_text(json.dumps({"enabled": True}))
    monkeypatch.setenv("JARVIS_WAKE_WORD", "0")
    assert ww.load_config(p)["enabled"] is False


def test_load_config_corrupt(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_WAKE_WORD", raising=False)
    p = tmp_path / "w.json"
    p.write_text("{bad")
    assert ww.load_config(p)["enabled"] is True


# ── engine ──────────────────────────────────────────────────────────────────

class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class FakeStream:
    def __init__(self, callback):
        self.callback = callback
        self.started = 0
        self.stopped = 0
        self.closed = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def close(self):
        self.closed += 1


def make_engine(**cfg):
    clock = FakeClock()
    config = ww.load_config.__wrapped__ if False else None
    base = {"enabled": True, "aliases": list(ww.DEFAULT_ALIASES),
            "fuzzy_threshold": ww.DEFAULT_FUZZY, "barge_in": True,
            "rms_threshold": 0.02, "min_speech_ms": 250,
            "cooldown_s": 1.5, "echo_guard_ms": 400}
    base.update(cfg)
    streams = []

    def factory(cb):
        s = FakeStream(cb)
        streams.append(s)
        return s

    eng = ww.WakeWordEngine(config=base, clock=clock, stream_factory=factory)
    return eng, clock, streams


def test_engine_transcript_fires_callback():
    eng, _, _ = make_engine()
    got = []
    eng.on_wake = got.append
    assert eng.handle_transcript("hey jarvis open chrome") == "open chrome"
    assert got == ["open chrome"]


def test_engine_transcript_no_match():
    eng, _, _ = make_engine()
    assert eng.handle_transcript("open chrome") is None


def test_engine_disabled():
    eng, _, _ = make_engine(enabled=False)
    assert eng.handle_transcript("jarvis open chrome") is None


def test_engine_barge_in_flow():
    eng, clock, _ = make_engine()
    fired = []
    eng.on_interrupt = lambda: fired.append(True)
    eng.speech_started()
    clock.t = 101.0
    assert eng.handle_audio([0.5] * 10) is False
    clock.t = 101.3
    assert eng.handle_audio([0.5] * 10) is True
    assert fired == [True]
    eng.speech_finished()
    assert eng.gate.speaking is False


def test_engine_barge_in_disabled():
    eng, clock, _ = make_engine(barge_in=False)
    eng.speech_started()
    clock.t = 105.0
    assert eng.handle_audio([0.9] * 10) is False


def test_engine_start_stop():
    eng, _, streams = make_engine()
    msg = eng.start()
    assert "Wake word active" in msg and eng.running
    assert streams[0].started == 1
    assert "already running" in eng.start()
    assert "stopped" in eng.stop()
    assert streams[0].stopped == 1 and streams[0].closed == 1
    assert eng.running is False


def test_engine_start_disabled():
    eng, _, _ = make_engine(enabled=False)
    assert "disabled" in eng.start()


def test_engine_stream_failure():
    def bad_factory(cb):
        raise OSError("no mic")

    eng = ww.WakeWordEngine(config={"enabled": True, "barge_in": True},
                            stream_factory=bad_factory)
    assert "Microphone unavailable" in eng.start()
    assert eng.running is False


def test_engine_callback_handles_frames():
    eng, clock, streams = make_engine()
    eng.start()
    eng.speech_started()
    clock.t = 200.0
    streams[0].callback([[0.5], [0.5]], 2, None, None)
    clock.t = 200.4
    streams[0].callback([[0.5], [0.5]], 2, None, None)
    assert eng.gate.interrupts == 1


def test_engine_status():
    eng, _, _ = make_engine()
    s = eng.status()
    assert "Wake word" in s and "Barge-in" in s and "Aliases" in s


def test_audio_available_env(monkeypatch):
    monkeypatch.setenv("JARVIS_NO_AUDIO", "1")
    assert ww.audio_available() is False


# ── tool entry point ────────────────────────────────────────────────────────

def test_control_test_match(monkeypatch):
    eng, _, _ = make_engine()
    monkeypatch.setattr(ww, "_engine", eng)
    out = ww.wake_word_control({"action": "test", "text": "jarvis open chrome"})
    assert "Wake word detected" in out and "open chrome" in out


def test_control_test_no_match(monkeypatch):
    eng, _, _ = make_engine()
    monkeypatch.setattr(ww, "_engine", eng)
    assert "No wake word" in ww.wake_word_control({"action": "test", "text": "hello"})


def test_control_test_needs_text(monkeypatch):
    eng, _, _ = make_engine()
    monkeypatch.setattr(ww, "_engine", eng)
    assert "some text" in ww.wake_word_control({"action": "test"})


def test_control_start_stop_status(monkeypatch):
    eng, _, _ = make_engine()
    monkeypatch.setattr(ww, "_engine", eng)
    assert "active" in ww.wake_word_control({"action": "start"})
    assert "running on port" not in ww.wake_word_control({"action": "status"})
    assert "stopped" in ww.wake_word_control({"action": "stop"})


def test_control_config(monkeypatch):
    eng, _, _ = make_engine()
    monkeypatch.setattr(ww, "_engine", eng)
    assert json.loads(ww.wake_word_control({"action": "config"}))["enabled"] is True


def test_control_unknown(monkeypatch):
    eng, _, _ = make_engine()
    monkeypatch.setattr(ww, "_engine", eng)
    assert "Unknown wake-word action" in ww.wake_word_control({"action": "zzz"})
