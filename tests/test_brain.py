"""
Offline tests for VINCEVISION Brain 2.0.

No API keys, no network, no PyQt6 / audio required — every LLM call is
mocked. Run:  python -m pytest -q tests/test_brain.py
"""

import json

import pytest

from agent import planner, executor
from core import long_term_memory as ltm


# ════════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════════

@pytest.fixture
def memdb(tmp_path, monkeypatch):
    """Point the memory store at a throwaway database."""
    monkeypatch.setattr(ltm, "DB_PATH", tmp_path / "mem.db")
    monkeypatch.setattr(ltm, "_FTS_OK", None)
    return ltm


def _ok(text):
    return {"success": True, "text": text, "error": "", "provider": "mock", "model": "mock"}


def _fail(err="no key"):
    return {"success": False, "text": "", "error": err, "provider": "None", "model": "None"}


# ════════════════════════════════════════════════════════════════
# Planner: JSON extraction
# ════════════════════════════════════════════════════════════════

def test_extract_json_plain():
    assert planner._extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    assert planner._extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_with_prose():
    assert planner._extract_json('Here you go:\n{"a": 1}\nHope that helps!') == {"a": 1}


def test_extract_json_invalid_raises():
    with pytest.raises(Exception):
        planner._extract_json("not json at all")


# ════════════════════════════════════════════════════════════════
# Planner: normalization
# ════════════════════════════════════════════════════════════════

def test_normalize_renumbers_and_clamps():
    raw = {"steps": [{"step": 99, "tool": "web_search", "parameters": {"query": f"q{i}"}}
                     for i in range(12)]}
    plan = planner._normalize_plan(raw, "goal")
    assert len(plan["steps"]) == planner.MAX_STEPS
    assert [s["step"] for s in plan["steps"]] == list(range(1, planner.MAX_STEPS + 1))
    assert plan["success_criteria"] == "goal"


def test_normalize_replaces_generated_code():
    raw = {"steps": [{"tool": "generated_code", "description": "do a thing", "parameters": {}}]}
    plan = planner._normalize_plan(raw, "goal")
    assert plan["steps"][0]["tool"] == "web_search"
    assert plan["steps"][0]["parameters"]["query"] == "do a thing"


def test_normalize_strips_self_and_forward_refs():
    raw = {"steps": [
        {"tool": "web_search", "parameters": {"query": "{{step1}} {{step2}} {{step0}}"}},
        {"tool": "file_controller", "parameters": {"content": "{{step1}} {{step3}}"}},
    ]}
    plan = planner._normalize_plan(raw, "goal")
    # step 1 may not reference anything
    assert "{{" not in plan["steps"][0]["parameters"]["query"]
    # step 2 keeps the valid back-ref, drops the forward ref
    assert "{{step1}}" in plan["steps"][1]["parameters"]["content"]
    assert "{{step3}}" not in plan["steps"][1]["parameters"]["content"]
    assert plan["steps"][1]["depends_on"] == [1]


def test_normalize_invalid_raises():
    with pytest.raises(ValueError):
        planner._normalize_plan({"steps": []}, "goal")
    with pytest.raises(ValueError):
        planner._normalize_plan("nope", "goal")


def test_fallback_plan_shape():
    plan = planner._fallback_plan("find bitcoin price")
    assert plan["steps"][0]["tool"] == "web_search"
    assert plan["steps"][0]["parameters"]["query"] == "find bitcoin price"


# ════════════════════════════════════════════════════════════════
# Planner: routing (mocked LLM)
# ════════════════════════════════════════════════════════════════

def test_create_plan_falls_back_when_router_fails(monkeypatch):
    monkeypatch.setattr(planner, "ask_ai", lambda *a, **k: _fail())
    plan = planner.create_plan("anything")
    assert plan["steps"][0]["tool"] == "web_search"


def test_create_plan_parses_router_success(monkeypatch):
    raw = {
        "goal": "g", "success_criteria": "done",
        "steps": [
            {"step": 1, "tool": "web_search", "parameters": {"query": "x"}},
            {"step": 2, "tool": "file_controller",
             "parameters": {"action": "write", "content": "{{step1}}"}},
        ],
    }
    monkeypatch.setattr(planner, "ask_ai", lambda *a, **k: _ok(json.dumps(raw)))
    plan = planner.create_plan("g")
    assert len(plan["steps"]) == 2
    assert plan["steps"][1]["depends_on"] == [1]


def test_replan_includes_feedback(monkeypatch):
    captured = {}

    def fake(prompt, **kw):
        captured["prompt"] = prompt
        return _ok(json.dumps({"steps": [{"tool": "web_search", "parameters": {"query": "y"}}]}))

    monkeypatch.setattr(planner, "ask_ai", fake)
    planner.replan("g", [], {"tool": "t", "description": "d"}, "err", feedback="MISSING-XYZ")
    assert "MISSING-XYZ" in captured["prompt"]


# ════════════════════════════════════════════════════════════════
# Executor: data-flow resolution
# ════════════════════════════════════════════════════════════════

def test_resolve_refs_nested():
    params = {
        "content": "A={{step1}} B={{step2}}",
        "list": ["{{step1}}", 7, {"deep": "{{step2}}"}],
        "num": 42,
    }
    out = executor._resolve_refs(params, {1: "ONE", 2: "TWO"})
    assert out["content"] == "A=ONE B=TWO"
    assert out["list"][0] == "ONE"
    assert out["list"][1] == 7
    assert out["list"][2]["deep"] == "TWO"
    assert out["num"] == 42


def test_resolve_refs_missing_becomes_empty():
    out = executor._resolve_refs({"x": "before{{step9}}after"}, {1: "ONE"})
    assert out["x"] == "beforeafter"


def test_resolve_refs_truncates_long_output():
    big = "z" * (executor.MAX_REF_CHARS + 500)
    out = executor._resolve_refs("{{step1}}", {1: big})
    assert len(out) == executor.MAX_REF_CHARS


# ════════════════════════════════════════════════════════════════
# Executor: verification + end-to-end (mocked)
# ════════════════════════════════════════════════════════════════

def test_verify_fails_open_when_router_down(monkeypatch):
    monkeypatch.setattr(executor, "ask_ai", lambda *a, **k: _fail())
    verdict = executor.AgentExecutor()._verify_goal("g", {}, {})
    assert verdict["satisfied"] is True


def test_verify_detects_unsatisfied(monkeypatch):
    monkeypatch.setattr(executor, "ask_ai",
                        lambda *a, **k: _ok('{"satisfied": false, "missing": "file empty"}'))
    verdict = executor.AgentExecutor()._verify_goal("g", {}, {1: "Done."})
    assert verdict["satisfied"] is False
    assert verdict["missing"] == "file empty"


def test_execute_dataflow_end_to_end(monkeypatch, memdb):
    raw_plan = {
        "goal": "research and save", "success_criteria": "file has research",
        "steps": [
            {"step": 1, "tool": "web_search", "parameters": {"query": "topic"}},
            {"step": 2, "tool": "file_controller",
             "parameters": {"action": "write", "name": "out.txt", "content": "{{step1}}"}},
        ],
    }
    monkeypatch.setattr(planner, "ask_ai", lambda *a, **k: _ok(json.dumps(raw_plan)))

    calls = []

    def fake_call(tool, params, speak):
        calls.append((tool, dict(params)))
        return f"RESULT-{tool}"

    monkeypatch.setattr(executor, "_call_tool", fake_call)

    def fake_ask(prompt, system="", **kw):
        if system == executor.VERIFIER_PROMPT:
            return _ok('{"satisfied": true, "missing": ""}')
        return _ok("All done, sir.")

    monkeypatch.setattr(executor, "ask_ai", fake_ask)

    result = executor.AgentExecutor().execute("research and save")

    assert result == "All done, sir."
    assert len(calls) == 2
    # the flagship feature: step 2 received step 1's real output
    assert calls[1][1]["content"] == "RESULT-web_search"
    # and the task was recorded in long-term memory
    assert any(i["kind"] == "task" for i in memdb.recent(limit=10))


# ════════════════════════════════════════════════════════════════
# Long-term memory
# ════════════════════════════════════════════════════════════════

def test_remember_and_recall(memdb):
    memdb.remember("Nairobi weather is usually sunny", kind="fact", tags="weather")
    hits = memdb.recall("Nairobi")
    assert hits and "Nairobi" in hits[0]["text"]


def test_recall_empty_returns_recent(memdb):
    memdb.remember("first fact")
    memdb.remember("second fact")
    hits = memdb.recall("", limit=2)
    assert len(hits) == 2


def test_preference_upsert_no_duplicates(memdb):
    memdb.remember_preference("language", "English")
    memdb.remember_preference("language", "Swahili")
    prefs = memdb.get_preferences()
    assert len(prefs) == 1
    assert "Swahili" in prefs[0]["text"]


def test_learn_from_task(memdb):
    memdb.learn_from_task("book a flight", [{"step": 1}], "booked", success=True)
    tasks = memdb.recall("flight", kinds=["task"])
    assert tasks and tasks[0]["kind"] == "task"


def test_recall_survives_weird_query(memdb):
    memdb.remember("some fact about cats")
    # FTS syntax characters must not crash the store
    assert isinstance(memdb.recall('cats AND OR "*( '), list)


def test_format_for_prompt_bounded(memdb):
    items = [{"kind": "fact", "text": "x" * 5000} for _ in range(20)]
    out = memdb.format_for_prompt(items)
    assert len(out) <= memdb.MAX_PROMPT_CHARS + 50
    assert memdb.format_for_prompt([]) == ""


def test_compat_shim_roundtrip(memdb):
    memdb.update_memory({"preferences": {"city": {"value": "Nairobi"}}})
    loaded = memdb.load_memory()
    assert loaded["preferences"]["city"]["value"] == "Nairobi"
    rendered = memdb.format_memory_for_prompt(loaded)
    assert "Nairobi" in rendered
