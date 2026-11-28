"""Offline tests for the crash net (core/safe_run.py).

The promise: a tool NEVER raises into the session, failures are readable,
and the crash log stays bounded.
"""

import pytest

from core import safe_run as sr


@pytest.fixture
def log(tmp_path, monkeypatch):
    path = tmp_path / "crashes.log"
    monkeypatch.setattr(sr, "CRASH_LOG", path)
    # log_crash resolves _base_dir()/CRASH_LOG, so point the base at tmp too.
    monkeypatch.setattr(sr, "_base_dir", lambda: tmp_path)
    return path


class Player:
    def __init__(self, explode=False):
        self.lines = []
        self.explode = explode

    def write_log(self, text):
        if self.explode:
            raise RuntimeError("UI is broken")
        self.lines.append(text)


# ── install hints ──────────────────────────────────────────────────────────

def test_install_hint_playwright():
    exc = ModuleNotFoundError("no module", name="playwright")
    assert "pip install playwright" in sr.install_hint(exc)


def test_install_hint_nested_module():
    exc = ModuleNotFoundError("no module", name="google.genai")
    assert "google-genai" in sr.install_hint(exc)


def test_install_hint_unknown():
    assert sr.install_hint(ModuleNotFoundError("x", name="weirdpkg")) == ""


def test_install_hint_plain_error():
    assert sr.install_hint(ValueError("x")) == ""


def test_install_hint_no_name():
    assert sr.install_hint(ModuleNotFoundError("x")) == ""


# ── friendly messages ──────────────────────────────────────────────────────

def test_friendly_contains_type_and_detail():
    msg = sr.friendly("hotel_manager", ValueError("bad city"))
    assert "hotel_manager" in msg and "ValueError" in msg and "bad city" in msg


def test_friendly_reassures_session_alive():
    assert "session is still running" in sr.friendly("x", RuntimeError("boom"))


def test_friendly_truncates_long_detail():
    msg = sr.friendly("x", RuntimeError("z" * 500))
    assert len(msg) < 450 and "…" in msg


def test_friendly_empty_detail_falls_back_to_type():
    assert "RuntimeError" in sr.friendly("x", RuntimeError())


def test_friendly_includes_install_hint():
    msg = sr.friendly("browser", ModuleNotFoundError("x", name="selenium"))
    assert "pip install selenium" in msg


# ── guard ──────────────────────────────────────────────────────────────────

def test_guard_returns_value():
    assert sr.guard(lambda a, b: a + b, 2, 3) == 5


def test_guard_kwargs():
    assert sr.guard(lambda x=0: x * 2, x=4) == 8


def test_guard_swallows_exception(log):
    def boom():
        raise ValueError("nope")
    assert sr.guard(boom, default="fallback", label="t") == "fallback"
    assert log.exists()


def test_guard_default_none(log):
    assert sr.guard(lambda: 1 / 0, label="t") is None


def test_guard_reraises_keyboard_interrupt():
    with pytest.raises(KeyboardInterrupt):
        sr.guard(lambda: (_ for _ in ()).throw(KeyboardInterrupt()))


def test_guard_reraises_system_exit():
    with pytest.raises(SystemExit):
        sr.guard(lambda: (_ for _ in ()).throw(SystemExit(1)))


# ── safe_tool ──────────────────────────────────────────────────────────────

def test_safe_tool_passthrough():
    @sr.safe_tool("t")
    def tool(parameters, player=None, speak=None):
        return "fine"
    assert tool({}) == "fine"


def test_safe_tool_none_becomes_done():
    @sr.safe_tool("t")
    def tool(parameters, player=None, speak=None):
        return None
    assert tool({}) == "Done."


def test_safe_tool_coerces_non_string():
    @sr.safe_tool("t")
    def tool(parameters, player=None, speak=None):
        return {"a": 1}
    assert isinstance(tool({}), str)


def test_safe_tool_catches_exception(log):
    @sr.safe_tool("t")
    def tool(parameters, player=None, speak=None):
        raise RuntimeError("kaboom")
    out = tool({})
    assert "kaboom" in out and "session is still running" in out


def test_safe_tool_notifies_player(log):
    p = Player()

    @sr.safe_tool("t")
    def tool(parameters, player=None, speak=None):
        raise RuntimeError("x")
    tool({}, player=p)
    assert p.lines and "problem" in p.lines[0]


def test_safe_tool_positional_player(log):
    p = Player()

    @sr.safe_tool("t")
    def tool(parameters, player=None, speak=None):
        raise RuntimeError("x")
    tool({}, p)
    assert p.lines


def test_safe_tool_speaks(log):
    said = []

    @sr.safe_tool("t")
    def tool(parameters, player=None, speak=None):
        raise RuntimeError("x")
    tool({}, speak=said.append)
    assert said and "kept running" in said[0]


def test_safe_tool_survives_broken_player(log):
    @sr.safe_tool("t")
    def tool(parameters, player=None, speak=None):
        raise RuntimeError("x")
    out = tool({}, player=Player(explode=True))
    assert isinstance(out, str) and "problem" in out


def test_safe_tool_survives_broken_speak(log):
    def bad_speak(_):
        raise OSError("no audio")

    @sr.safe_tool("t")
    def tool(parameters, player=None, speak=None):
        raise RuntimeError("x")
    assert isinstance(tool({}, speak=bad_speak), str)


def test_safe_tool_notify_false(log):
    p = Player()

    @sr.safe_tool("t", notify=False)
    def tool(parameters, player=None, speak=None):
        raise RuntimeError("x")
    tool({}, player=p)
    assert p.lines == []


def test_safe_tool_reraises_keyboard_interrupt():
    @sr.safe_tool("t")
    def tool(parameters, player=None, speak=None):
        raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        tool({})


def test_safe_tool_reraises_system_exit():
    @sr.safe_tool("t")
    def tool(parameters, player=None, speak=None):
        raise SystemExit(2)
    with pytest.raises(SystemExit):
        tool({})


def test_safe_tool_preserves_metadata():
    @sr.safe_tool("label")
    def my_tool(parameters, player=None, speak=None):
        """Docstring."""
        return "x"
    assert my_tool.__name__ == "my_tool"
    assert my_tool.__doc__ == "Docstring."


def test_safe_tool_default_label_is_fn_name(log):
    @sr.safe_tool()
    def widget(parameters, player=None, speak=None):
        raise ValueError("v")
    assert "widget" in widget({})


def test_safe_tool_bad_parameters_type(log):
    @sr.safe_tool("t")
    def tool(parameters, player=None, speak=None):
        return str(parameters.get("action"))
    out = tool(None)          # AttributeError inside → contained
    assert "AttributeError" in out


# ── crash log ──────────────────────────────────────────────────────────────

def test_log_crash_writes_header(log):
    sr.log_crash("label", ValueError("v"))
    text = log.read_text(encoding="utf-8")
    assert "label: ValueError: v" in text


def test_log_crash_appends(log):
    sr.log_crash("a", ValueError("1"))
    sr.log_crash("b", ValueError("2"))
    assert len(sr.read_crashes()) == 2


def test_log_crash_never_raises_on_bad_path(tmp_path):
    bad = tmp_path / "file.txt"
    bad.write_text("x", encoding="utf-8")
    sr.log_crash("x", ValueError("v"), path=bad / "nested" / "log")  # must not raise


def test_log_crash_bounds_size(log, monkeypatch):
    monkeypatch.setattr(sr, "_base_dir", lambda: log.parent)
    monkeypatch.setattr(sr, "MAX_LOG_BYTES", 200)
    monkeypatch.setattr(sr, "MAX_ENTRIES", 3)
    for i in range(40):
        sr.log_crash(f"e{i}", ValueError("x" * 40))
    assert log.stat().st_size < 20000
    assert len(sr.read_crashes(limit=100)) <= 40


def test_read_crashes_limit(log):
    for i in range(8):
        sr.log_crash(f"e{i}", ValueError("x"))
    rows = sr.read_crashes(limit=3)
    assert len(rows) == 3 and "e7" in rows[-1]


def test_read_crashes_missing_file(log):
    assert sr.read_crashes() == []


def test_read_crashes_zero_limit_clamped(log):
    sr.log_crash("e", ValueError("x"))
    assert len(sr.read_crashes(limit=0)) == 1


def test_crash_stats_empty(log):
    stats = sr.crash_stats()
    assert stats["total"] == 0 and stats["recent"] == []


def test_crash_stats_counts(log):
    for i in range(7):
        sr.log_crash(f"e{i}", ValueError("x"))
    stats = sr.crash_stats()
    assert stats["total"] == 7 and len(stats["recent"]) == 5


def test_crash_stats_never_raises(tmp_path):
    assert isinstance(sr.crash_stats(path=tmp_path / "no" / "dir.log"), dict)


# ── health_control tool surface ────────────────────────────────────────────

def test_health_status_clean(log):
    assert "healthy" in sr.health_control({"action": "status"})


def test_health_status_with_crashes(log):
    sr.log_crash("x", ValueError("v"))
    out = sr.health_control({"action": "status"})
    assert "contained" in out


def test_health_crashes_empty(log):
    assert "No crashes" in sr.health_control({"action": "crashes"})


def test_health_crashes_lists(log):
    sr.log_crash("hotel_manager", ValueError("v"))
    assert "hotel_manager" in sr.health_control({"action": "log", "limit": 5})


def test_health_clear(log):
    sr.log_crash("x", ValueError("v"))
    assert "cleared" in sr.health_control({"action": "clear"})
    assert sr.crash_stats()["total"] == 0


def test_health_deps_lists_modules(log):
    out = sr.health_control({"action": "deps"})
    assert "playwright" in out and "Dependencies" in out


def test_health_none_params(log):
    assert isinstance(sr.health_control(None), str)


def test_health_unknown_action(log):
    assert isinstance(sr.health_control({"action": "zzz"}), str)


def test_health_is_itself_safe(log, monkeypatch):
    monkeypatch.setattr(sr, "crash_stats", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bad")))
    out = sr.health_control({"action": "status"})
    assert "problem" in out


def test_guard_none_callback_is_noop(log):
    # Optional UI/speech hooks are absent in headless runs — not a crash.
    assert sr.guard(None, "message", default="d", label="t") == "d"
    assert not log.exists()


def test_guard_non_callable_is_noop(log):
    assert sr.guard("not callable", default=7) == 7
    assert not log.exists()


def test_safe_tool_no_player_logs_one_entry(log):
    @sr.safe_tool("t")
    def tool(parameters, player=None, speak=None):
        raise RuntimeError("x")
    tool({})
    assert len(sr.read_crashes(limit=50)) == 1


def test_safe_tool_broken_callbacks_log_separately(log):
    @sr.safe_tool("t")
    def tool(parameters, player=None, speak=None):
        raise RuntimeError("x")
    tool({}, player=Player(explode=True))
    # the tool failure + the broken UI hook, but no bogus NoneType entries
    heads = sr.read_crashes(limit=50)
    assert len(heads) == 2
    assert not any("NoneType" in h for h in heads)
