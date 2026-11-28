"""Offline tests for the agent builder (core/agent_builder.py).

Generated agents must compile, import, run, and be crash-proof — and the
builder must refuse to overwrite existing modules or generate offensive tools.
Everything writes into tmp_path.
"""

import importlib.util
import json

import pytest

from core import agent_builder as ab


@pytest.fixture
def base(tmp_path, monkeypatch):
    (tmp_path / "actions").mkdir()
    (tmp_path / "tests").mkdir()
    monkeypatch.setattr(ab, "_base_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def spec():
    return ab.parse_spec("Build an agent called crypto_watch with actions search, track, alert")


def load_module(path, name):
    s = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(s)
    s.loader.exec_module(mod)
    return mod


# ── slugify + name validation ───────────────────────────────────────────────

def test_slugify_spaces():
    assert ab.slugify("Crypto Watch") == "crypto_watch"


def test_slugify_punctuation():
    assert ab.slugify("my-agent!!") == "my_agent"


def test_slugify_empty():
    assert ab.slugify("") == ""
    assert ab.slugify(None) == ""


def test_slugify_length_cap():
    assert len(ab.slugify("x" * 200)) <= ab.MAX_NAME_LEN


def test_validate_name_adds_suffix(base):
    ok, name = ab.validate_name("crypto_watch")
    assert ok and name == "crypto_watch_agent"


def test_validate_name_keeps_agent_suffix(base):
    ok, name = ab.validate_name("price_agent")
    assert ok and name == "price_agent"


def test_validate_name_keeps_manager_suffix(base):
    ok, name = ab.validate_name("hotel_manager")
    assert ok and name == "hotel_manager"


def test_validate_name_empty(base):
    assert ab.validate_name("")[0] is False


def test_validate_name_too_short(base):
    assert ab.validate_name("ab")[0] is False


def test_validate_name_bad_start(base):
    assert ab.validate_name("1agent")[0] is False


def test_validate_name_bad_chars(base):
    assert ab.validate_name("my agent!")[0] is False


def test_validate_name_keyword(base):
    assert ab.validate_name("class")[0] is False


def test_validate_name_reserved(base):
    assert ab.validate_name("main")[0] is False


def test_validate_name_existing_module(base):
    (base / "actions" / "taken_agent.py").write_text("x=1", encoding="utf-8")
    ok, msg = ab.validate_name("taken_agent")
    assert not ok and "already exists" in msg


def test_validate_name_does_not_overwrite_real_modules(base):
    ok, msg = ab.validate_name("flight_manager")
    assert ok is True or "already exists" in msg


# ── blocked specs ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "build a keylogger agent", "make a phishing agent", "create a wifi jammer agent",
    "build an agent to steal credentials", "make a ddos agent",
])
def test_blocked_specs_detected(text):
    assert ab.is_blocked_spec(text) != ""


def test_benign_spec_not_blocked():
    assert ab.is_blocked_spec("build a crypto price agent with search and alert") == ""


def test_blocked_spec_refused(base):
    spec = ab.parse_spec("build a keylogger agent with actions track")
    res = ab.build_agent(spec, dry_run=False, base_dir=base)
    assert not res["ok"] and "out of scope" in res["error"]


def test_blocked_spec_writes_nothing(base):
    spec = ab.parse_spec("build a phishing agent")
    ab.build_agent(spec, dry_run=False, base_dir=base)
    assert list((base / "actions").glob("*.py")) == []


# ── parse_spec ─────────────────────────────────────────────────────────────

def test_parse_spec_named(spec):
    assert spec["name"] == "crypto_watch"


def test_parse_spec_actions(spec):
    assert spec["actions"] == ["search", "track", "alert"]


def test_parse_spec_create_an_agent():
    s = ab.parse_spec("create a weather agent")
    assert s["name"] == "weather"


def test_parse_spec_explicit_actions_list():
    s = ab.parse_spec("", name="myagent", actions=["search", "alert"])
    assert s["actions"] == ["search", "alert"]


def test_parse_spec_actions_csv():
    s = ab.parse_spec("", name="myagent", actions="search, alert, report")
    assert s["actions"] == ["search", "alert", "report"]


def test_parse_spec_actions_colon_syntax():
    s = ab.parse_spec("build an agent called thingy. actions: search, notify")
    assert "notify" in s["actions"]


def test_parse_spec_infers_verbs():
    s = ab.parse_spec("build an agent called newsy that should search and alert me")
    assert "search" in s["actions"] and "alert" in s["actions"]


def test_parse_spec_default_actions():
    s = ab.parse_spec("", name="blanky")
    assert s["actions"] == ["search", "save", "list"]


def test_parse_spec_dedupes():
    s = ab.parse_spec("", name="x", actions=["search", "search"])
    assert s["actions"] == ["search"]


def test_parse_spec_drops_help_status():
    s = ab.parse_spec("", name="x", actions=["help", "status", "search"])
    assert s["actions"] == ["search"]


def test_parse_spec_caps_actions():
    s = ab.parse_spec("", name="x", actions=[f"a{i}" for i in range(30)])
    assert len(s["actions"]) <= ab.MAX_ACTIONS


def test_parse_spec_description_kept():
    s = ab.parse_spec("build a crypto agent", description="Tracks coins")
    assert s["description"] == "Tracks coins"


# ── capability mapping ─────────────────────────────────────────────────────

@pytest.mark.parametrize("action,handler", [
    ("search", "web_search"), ("research", "web_search"), ("lookup", "web_search"),
    ("open", "browser"), ("browse", "browser"), ("visit", "browser"),
    ("alert", "alerts"), ("notify", "alerts"), ("remind", "alerts"),
    ("report", "report"), ("summarize", "report"),
    ("track", "store"), ("save", "store"), ("list", "store"),
])
def test_infer_handler(action, handler):
    assert ab.infer_handler(action) == handler


def test_infer_handler_unknown_defaults_store():
    assert ab.infer_handler("zzz") == "store"


# ── compile check ──────────────────────────────────────────────────────────

def test_compile_check_valid():
    assert ab.compile_check("x = 1\n")[0] is True


def test_compile_check_invalid():
    ok, err = ab.compile_check("def broken(:\n")
    assert not ok and "line" in err


# ── rendering ──────────────────────────────────────────────────────────────

def test_render_agent_compiles(spec):
    src = ab.render_agent(dict(spec, name="crypto_watch_agent"))
    assert ab.compile_check(src)[0] is True


def test_render_agent_has_dispatcher(spec):
    src = ab.render_agent(dict(spec, name="crypto_watch_agent"))
    assert "@safe_tool(\"crypto_watch_agent\")" in src
    assert "def crypto_watch_agent(parameters" in src


def test_render_agent_no_shell_exec(spec):
    src = ab.render_agent(dict(spec, name="crypto_watch_agent"))
    for danger in ("os.system", "subprocess", "eval(", "exec(", "pickle"):
        assert danger not in src


def test_render_agent_lazy_imports(spec):
    src = ab.render_agent(dict(spec, name="crypto_watch_agent"))
    # capability imports must be inside functions, not at module top
    head = src.split("def _load")[0]
    assert "from actions.web_search" not in head
    assert "from actions.browser_control" not in head


def test_render_tests_compiles(spec):
    assert ab.compile_check(ab.render_tests(dict(spec, name="crypto_watch_agent")))[0] is True


def test_render_agent_handles_quotes_in_description():
    s = ab.parse_spec('build an agent called quotey', description='say """hello"""')
    assert ab.compile_check(ab.render_agent(dict(s, name="quotey_agent")))[0] is True


# ── build (dry run + real) ─────────────────────────────────────────────────

def test_build_dry_run_writes_nothing(base, spec):
    res = ab.build_agent(spec, dry_run=True, base_dir=base)
    assert res["ok"] and res["dry_run"]
    assert list((base / "actions").glob("*.py")) == []


def test_build_dry_run_returns_source(base, spec):
    res = ab.build_agent(spec, dry_run=True, base_dir=base)
    assert "def crypto_watch_agent" in res["source"]


def test_build_writes_files(base, spec):
    res = ab.build_agent(spec, dry_run=False, base_dir=base)
    assert res["ok"] is True
    assert (base / "actions" / "crypto_watch_agent.py").exists()
    assert (base / "tests" / "test_crypto_watch_agent.py").exists()


def test_build_registers(base, spec):
    ab.build_agent(spec, dry_run=False, base_dir=base)
    rows = ab.load_registry()
    assert len(rows) == 1 and rows[0]["name"] == "crypto_watch_agent"


def test_build_refuses_duplicate(base, spec):
    ab.build_agent(spec, dry_run=False, base_dir=base)
    res = ab.build_agent(spec, dry_run=False, base_dir=base)
    assert not res["ok"] and "already exists" in res["error"]


def test_build_bad_name(base):
    res = ab.build_agent(ab.parse_spec("", name="x"), dry_run=False, base_dir=base)
    assert not res["ok"]


def test_build_without_tests(base, spec):
    res = ab.build_agent(spec, dry_run=False, base_dir=base, write_tests=False)
    assert res["ok"] and not (base / "tests" / "test_crypto_watch_agent.py").exists()


def test_build_syntax_failure_writes_nothing(base, spec, monkeypatch):
    monkeypatch.setattr(ab, "render_agent", lambda s: "def broken(:\n")
    res = ab.build_agent(spec, dry_run=False, base_dir=base)
    assert not res["ok"] and "syntax check" in res["error"]
    assert list((base / "actions").glob("*.py")) == []


def test_build_test_syntax_failure_writes_nothing(base, spec, monkeypatch):
    monkeypatch.setattr(ab, "render_tests", lambda s: "def broken(:\n")
    res = ab.build_agent(spec, dry_run=False, base_dir=base)
    assert not res["ok"]
    assert list((base / "actions").glob("*.py")) == []


def test_build_write_failure_is_soft(base, spec, monkeypatch):
    monkeypatch.setattr(ab, "ACTIONS_DIR", ab.Path("actions"))
    blocker = base / "actions"
    import shutil
    shutil.rmtree(blocker)
    blocker.write_text("not a dir", encoding="utf-8")
    res = ab.build_agent(spec, dry_run=False, base_dir=base)
    assert not res["ok"] and "Could not write" in res["error"]


# ── generated agent behaviour ──────────────────────────────────────────────

@pytest.fixture
def generated(base, spec, tmp_path):
    res = ab.build_agent(spec, dry_run=False, base_dir=base)
    mod = load_module(res["path"], res["name"])
    mod.STORE_PATH = tmp_path / "gen_store.json"
    mod.REPORT_DIR = tmp_path / "gen_reports"
    return mod, res["name"]


def test_generated_help(generated):
    mod, name = generated
    assert "Crypto Watch Agent" in getattr(mod, name)({"action": "help"})


def test_generated_help_lists_actions(generated):
    mod, name = generated
    out = getattr(mod, name)({"action": "help"})
    assert "search" in out and "track" in out and "alert" in out


def test_generated_list_empty(generated):
    mod, name = generated
    assert "Nothing stored" in getattr(mod, name)({"action": "list"})


def test_generated_store_action(generated):
    mod, name = generated
    fn = getattr(mod, name)
    assert "Saved" in fn({"action": "track", "query": "BTC"})
    assert "BTC" in fn({"action": "list"})


def test_generated_action_needs_input(generated):
    mod, name = generated
    assert "Give me" in getattr(mod, name)({"action": "track"})


def test_generated_unknown_action(generated):
    mod, name = generated
    assert "Unknown action" in getattr(mod, name)({"action": "zzz"})


def test_generated_none_params(generated):
    mod, name = generated
    assert isinstance(getattr(mod, name)(None), str)


def test_generated_numeric_action(generated):
    mod, name = generated
    assert isinstance(getattr(mod, name)({"action": 123}), str)


def test_generated_is_crash_proof(generated, monkeypatch):
    mod, name = generated
    monkeypatch.setattr(mod, "_load", lambda: (_ for _ in ()).throw(RuntimeError("disk")))
    out = getattr(mod, name)({"action": "list"})
    assert "problem" in out and "session is still running" in out


def test_generated_report_action(base, tmp_path):
    spec = ab.parse_spec("", name="reporty", actions=["report"])
    res = ab.build_agent(spec, dry_run=False, base_dir=base)
    mod = load_module(res["path"], res["name"])
    mod.STORE_PATH = tmp_path / "s.json"
    mod.REPORT_DIR = tmp_path / "reports"
    out = getattr(mod, res["name"])({"action": "report", "text": "hello"})
    assert "Report saved" in out
    assert list((tmp_path / "reports").glob("*.md"))


def test_generated_alert_action_delegates(base, tmp_path, monkeypatch):
    import sys, types
    calls = []
    fake = types.ModuleType("core.alerts")
    fake.notify = lambda title, body, **kw: calls.append(title) or {"ok": True, "results": {"file": "ok"}}
    monkeypatch.setitem(sys.modules, "core.alerts", fake)
    spec = ab.parse_spec("", name="notifyr", actions=["alert"])
    res = ab.build_agent(spec, dry_run=False, base_dir=base)
    mod = load_module(res["path"], res["name"])
    mod.STORE_PATH = tmp_path / "s.json"
    out = getattr(mod, res["name"])({"action": "alert", "text": "price moved"})
    assert "Alert sent" in out and calls


def test_generated_search_action_delegates(base, tmp_path, monkeypatch):
    import sys, types
    fake = types.ModuleType("actions.web_search")
    fake.web_search = lambda params: "Search results for " + params["query"]
    monkeypatch.setitem(sys.modules, "actions.web_search", fake)
    spec = ab.parse_spec("", name="searchy", actions=["search"])
    res = ab.build_agent(spec, dry_run=False, base_dir=base)
    mod = load_module(res["path"], res["name"])
    mod.STORE_PATH = tmp_path / "s.json"
    out = getattr(mod, res["name"])({"action": "search", "query": "BTC price"})
    assert "BTC price" in out


def test_generated_browser_action_uses_visible(base, tmp_path, monkeypatch):
    import sys, types
    calls = []
    fake = types.ModuleType("actions.browser_control")
    fake.browser_control = lambda parameters, player=None: calls.append(parameters) or "opened"
    monkeypatch.setitem(sys.modules, "actions.browser_control", fake)
    spec = ab.parse_spec("", name="browsy", actions=["open"])
    res = ab.build_agent(spec, dry_run=False, base_dir=base)
    mod = load_module(res["path"], res["name"])
    mod.STORE_PATH = tmp_path / "s.json"
    getattr(mod, res["name"])({"action": "open", "url": "example.com"})
    assert calls and calls[0]["url"] == "https://example.com"
    assert calls[0]["headless"] is False


# ── registry + removal ─────────────────────────────────────────────────────

def test_load_registry_missing(base):
    assert ab.load_registry() == []


def test_load_registry_corrupt(base):
    (base / "memory").mkdir()
    (base / ab.REGISTRY).write_text("{bad", encoding="utf-8")
    assert ab.load_registry() == []


def test_remove_agent(base, spec):
    ab.build_agent(spec, dry_run=False, base_dir=base)
    res = ab.remove_agent("crypto_watch_agent")
    assert res["ok"] and len(res["removed"]) == 2
    assert not (base / "actions" / "crypto_watch_agent.py").exists()


def test_remove_agent_updates_registry(base, spec):
    ab.build_agent(spec, dry_run=False, base_dir=base)
    ab.remove_agent("crypto_watch_agent")
    assert ab.load_registry() == []


def test_remove_unknown_agent_refused(base):
    res = ab.remove_agent("flight_manager")
    assert not res["ok"] and "won't delete" in res["error"]


def test_remove_never_touches_untracked_file(base):
    target = base / "actions" / "important_agent.py"
    target.write_text("# keep me", encoding="utf-8")
    ab.remove_agent("important_agent")
    assert target.exists()


# ── dispatcher ─────────────────────────────────────────────────────────────

def test_dispatcher_help(base):
    out = ab.agent_builder({"action": "help"})
    assert "Agent Builder" in out and "preview" in out


def test_dispatcher_none_params(base):
    assert isinstance(ab.agent_builder(None), str)


def test_dispatcher_unknown_action(base):
    assert "Unknown builder action" in ab.agent_builder({"action": "zzz"})


def test_dispatcher_list_empty(base):
    assert "No agents built" in ab.agent_builder({"action": "list"})


def test_dispatcher_preview(base):
    out = ab.agent_builder({"action": "preview",
                            "spec": "build an agent called demo with actions search, alert"})
    assert "Preview" in out and "Would write" in out
    assert list((base / "actions").glob("*.py")) == []


def test_dispatcher_preview_shows_mapping(base):
    out = ab.agent_builder({"action": "preview", "name": "demo", "actions": "search,alert"})
    assert "web search" in out and "alert" in out


def test_dispatcher_build(base):
    out = ab.agent_builder({"action": "build", "name": "demo", "actions": "search,track"})
    assert "Built demo_agent" in out
    assert (base / "actions" / "demo_agent.py").exists()


def test_dispatcher_build_lists_generated_tests(base):
    out = ab.agent_builder({"action": "build", "name": "demo", "actions": "search"})
    assert "test_demo_agent.py" in out


def test_dispatcher_dry_run_flag(base):
    ab.agent_builder({"action": "build", "name": "demo", "actions": "search", "dry_run": True})
    assert list((base / "actions").glob("*.py")) == []


def test_dispatcher_list_after_build(base):
    ab.agent_builder({"action": "build", "name": "demo", "actions": "search"})
    assert "demo_agent" in ab.agent_builder({"action": "list"})


def test_dispatcher_remove(base):
    ab.agent_builder({"action": "build", "name": "demo", "actions": "search"})
    assert "Removed" in ab.agent_builder({"action": "remove", "name": "demo_agent"})


def test_dispatcher_remove_needs_name(base):
    assert "Which agent" in ab.agent_builder({"action": "remove"})


def test_dispatcher_blocked_request(base):
    out = ab.agent_builder({"action": "build", "spec": "build a keylogger agent"})
    assert "out of scope" in out


def test_dispatcher_is_crash_proof(base, monkeypatch):
    monkeypatch.setattr(ab, "parse_spec", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bad")))
    out = ab.agent_builder({"action": "build", "name": "demo"})
    assert "problem" in out and "session is still running" in out
