"""Offline integration tests for the v2 wiring.

Parses main.py / executor.py / planner.py with `ast` (never imports main.py,
which pulls in audio/GUI dependencies) and checks that every new tool is
declared, dispatched, and documented for the planner — plus that the executor
has an outer crash guard.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

NEW_TOOLS = ["hotel_manager", "trip_planner", "alerts_control",
             "agent_builder", "visible_control", "health_control"]


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def declarations():
    tree = ast.parse(read("main.py"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "TOOL_DECLARATIONS":
                    return ast.literal_eval(node.value)
    raise AssertionError("TOOL_DECLARATIONS not found")


# ── main.py ────────────────────────────────────────────────────────────────

def test_declarations_parse(declarations):
    assert len(declarations) > 50


def test_no_duplicate_declarations(declarations):
    names = [d["name"] for d in declarations]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("tool", NEW_TOOLS)
def test_tool_declared(declarations, tool):
    assert tool in [d["name"] for d in declarations]


@pytest.mark.parametrize("tool", NEW_TOOLS)
def test_declaration_has_action_param(declarations, tool):
    decl = next(d for d in declarations if d["name"] == tool)
    assert "action" in decl["parameters"]["properties"]
    assert "action" in decl["parameters"]["required"]


@pytest.mark.parametrize("tool", NEW_TOOLS)
def test_declaration_has_description(declarations, tool):
    decl = next(d for d in declarations if d["name"] == tool)
    assert len(decl["description"]) > 60


@pytest.mark.parametrize("tool", NEW_TOOLS)
def test_tool_imported(tool):
    assert f"import {tool}" in read("main.py")


@pytest.mark.parametrize("tool", NEW_TOOLS)
def test_tool_dispatched(tool):
    assert f'elif name == "{tool}":' in read("main.py")


@pytest.mark.parametrize("tool", NEW_TOOLS)
def test_dispatch_passes_ui_and_speak(tool):
    src = read("main.py")
    idx = src.index(f'elif name == "{tool}":')
    block = src[idx:idx + 400]
    assert "player=self.ui" in block and "speak=self.speak" in block


def test_main_has_outer_tool_guard():
    src = read("main.py")
    assert "Tool '" in src and "failed:" in src


def test_main_line_endings_preserved():
    raw = (ROOT / "main.py").read_bytes()
    assert raw.count(b"\r\n") > 0
    assert raw.count(b"\n") == raw.count(b"\r\n")


# ── executor ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tool", NEW_TOOLS)
def test_executor_dispatches(tool):
    assert f'elif tool == "{tool}":' in read("agent/executor.py")


def test_executor_has_outer_guard():
    src = read("agent/executor.py")
    assert "def _call_tool(" in src and "def _call_tool_inner(" in src
    idx = src.index("def _call_tool(")
    body = src[idx:src.index("def _call_tool_inner(")]
    assert "try:" in body and "except Exception" in body
    assert "log_crash" in body and "friendly" in body


def test_executor_guard_reraises_deliberate_stops():
    src = read("agent/executor.py")
    idx = src.index("def _call_tool(")
    body = src[idx:src.index("def _call_tool_inner(")]
    assert "(KeyboardInterrupt, SystemExit)" in body


def test_executor_guard_actually_contains_failure():
    from agent import executor
    original = executor._call_tool_inner
    try:
        executor._call_tool_inner = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        out = executor._call_tool("hotel_manager", {}, None)
        assert isinstance(out, str)
        assert "problem" in out and "session is still running" in out
    finally:
        executor._call_tool_inner = original


def test_executor_guard_passes_through_success():
    from agent import executor
    original = executor._call_tool_inner
    try:
        executor._call_tool_inner = lambda *a, **k: "all good"
        assert executor._call_tool("hotel_manager", {}, None) == "all good"
    finally:
        executor._call_tool_inner = original


def test_executor_guard_survives_broken_speak():
    from agent import executor
    original = executor._call_tool_inner

    def bad_speak(_):
        raise OSError("no audio")
    try:
        executor._call_tool_inner = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
        assert isinstance(executor._call_tool("trip_planner", {}, bad_speak), str)
    finally:
        executor._call_tool_inner = original


def test_executor_guard_reraises_keyboard_interrupt():
    from agent import executor
    original = executor._call_tool_inner
    try:
        executor._call_tool_inner = lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt())
        with pytest.raises(KeyboardInterrupt):
            executor._call_tool("hotel_manager", {}, None)
    finally:
        executor._call_tool_inner = original


def test_executor_line_endings_lf():
    assert b"\r\n" not in (ROOT / "agent/executor.py").read_bytes()


# ── planner catalog ────────────────────────────────────────────────────────

@pytest.mark.parametrize("tool", NEW_TOOLS)
def test_planner_documents_tool(tool):
    assert f"\n{tool}\n" in read("agent/planner.py")


@pytest.mark.parametrize("tool", NEW_TOOLS)
def test_planner_entry_before_examples(tool):
    src = read("agent/planner.py")
    assert src.index(f"\n{tool}\n") < src.index("EXAMPLES:")


def test_planner_documents_key_params():
    src = read("agent/planner.py")
    for token in ("HOTEL CONFIRMED", "min_rating", "travellers", "min_level"):
        assert token in src


# ── crash-net coverage of the new modules ──────────────────────────────────

@pytest.mark.parametrize("module,fname", [
    ("actions/hotel_manager.py", "hotel_manager"),
    ("actions/trip_planner.py", "trip_planner"),
    ("core/alerts.py", "alerts_control"),
    ("core/agent_builder.py", "agent_builder"),
])
def test_new_dispatchers_are_safe_tooled(module, fname):
    tree = ast.parse(read(module))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == fname)
    decorators = [ast.unparse(d) for d in fn.decorator_list]
    assert any("safe_tool" in d for d in decorators)


@pytest.mark.parametrize("module", [
    "core/safe_run.py", "core/visible.py", "core/alerts.py",
    "core/agent_builder.py", "actions/hotel_manager.py", "actions/trip_planner.py",
])
def test_new_modules_are_stdlib_only_at_import(module):
    """CI installs only pytest — third-party imports must be lazy."""
    tree = ast.parse(read(module))
    allowed = {"json", "re", "time", "os", "sys", "ast", "keyword", "functools",
               "traceback", "uuid", "threading", "argparse", "datetime", "pathlib",
               "urllib", "http", "core", "actions", "agent", "typing", "__future__",
               "importlib", "collections", "math", "random", "string", "textwrap"}
    for node in tree.body:            # module level only
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in allowed, f"{module}: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root in allowed, f"{module}: from {node.module}"


def test_hotel_search_forces_visible_browser():
    src = read("actions/hotel_manager.py")
    assert "from core.visible import" in src
    assert '"headless": False' in src


def test_trip_planner_delegates_visible_search():
    src = read("actions/trip_planner.py")
    assert "from core.visible import Narrator" in src
    # It searches through the managers that force a visible browser.
    assert '"action": "compare"' in src
    assert "fm.flight_manager" in src and "hm.hotel_manager" in src


def test_flight_manager_uses_visible_layer():
    src = read("actions/flight_manager.py")
    assert "from core.visible import visible" in src
    assert "_narrator" in src


def test_flight_watch_pushes_alerts():
    assert "_push_alert" in read("actions/flight_manager.py")


def test_hotel_watch_pushes_alerts():
    assert "_alerts().notify" in read("actions/hotel_manager.py")


# ── no payment automation anywhere new ─────────────────────────────────────

@pytest.mark.parametrize("module", ["actions/hotel_manager.py", "actions/trip_planner.py"])
def test_no_card_data_entry(module):
    src = read(module).lower()
    assert "card data" in src or "payment details" in src
    for danger in ("fill_card", "enter_card", "cvv", "card_number"):
        assert danger not in src


def test_agent_builder_blocks_offensive_specs():
    from core.agent_builder import is_blocked_spec
    assert is_blocked_spec("build a keylogger agent")
    assert is_blocked_spec("make a phishing kit agent")
    assert not is_blocked_spec("build a hotel price agent")
