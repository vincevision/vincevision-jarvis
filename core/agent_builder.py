"""
Agent Builder for JARVIS — describe an agent, get a working agent
──────────────────────────────────────────────────────────────────
    "Build an agent called crypto_watch with actions search, track, alert"

It writes a real, importable module into actions/, plus an offline test file,
and wires nothing behind your back — you review the preview first.

Generated agents are safe by construction:
  * stdlib-only at import time (all capability imports are lazy)
  * wrapped in core.safe_run.safe_tool, so they cannot crash the session
  * actions are mapped to *existing, already-guarded* capabilities
    (web search, visible browser, alerts, local JSON store)
  * no shell execution, no code evaluation, no credential handling

Safety: names must be valid identifiers, cannot shadow an existing module or
a Python keyword, and specs requesting offensive capabilities are refused.
Every generated file is compile-checked before it is written.
"""

from __future__ import annotations

import ast
import json
import keyword
import re
import time
from datetime import datetime
from pathlib import Path

from core.safe_run import guard, safe_tool

ACTIONS_DIR = Path("actions")
TESTS_DIR = Path("tests")
REGISTRY = Path("memory") / "generated_agents.json"

RESERVED = {
    "main", "ui", "conftest", "setup", "doctor", "uninstall", "os", "sys",
    "json", "time", "re", "pathlib", "typing", "test", "tests", "core",
    "agent", "actions", "memory", "config", "logs", "reports",
}

# Standing constraint: no offensive tooling is generated.
_BLOCKED = (
    "keylog", "phish", "jammer", "jam wifi", "deauth", "piracy", "crack password",
    "steal", "credential harvest", "ddos", "botnet", "ransom", "stalk",
    "trace person", "find someone's address", "dox", "spyware", "rat tool",
)

MAX_ACTIONS = 12
MAX_NAME_LEN = 40


def _base_dir() -> Path:
    return Path(__file__).resolve().parent.parent


# ── Spec parsing ────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")
    return s[:MAX_NAME_LEN]


def validate_name(name: str, actions_dir=None) -> tuple[bool, str]:
    n = str(name or "").strip().lower()
    if not n:
        return False, "Give the agent a name."
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,39}", n):
        return False, ("Name must be 3–40 chars, start with a letter, and use only "
                       "letters, digits and underscores.")
    if keyword.iskeyword(n) or n in RESERVED:
        return False, f"'{n}' is a reserved name."
    if not n.endswith("_agent") and not n.endswith("_manager"):
        n = n + "_agent"
    directory = Path(actions_dir) if actions_dir else _base_dir() / ACTIONS_DIR
    try:
        if (directory / f"{n}.py").exists():
            return False, f"'{n}' already exists — pick another name."
    except OSError:
        pass
    return True, n


def is_blocked_spec(text: str) -> str:
    low = str(text or "").lower()
    for term in _BLOCKED:
        if term in low:
            return term
    return ""


def parse_spec(text: str = "", name: str = "", actions=None,
               description: str = "") -> dict:
    """Turn a plain-English request into a build spec."""
    raw = str(text or "").strip()
    blocked = is_blocked_spec(raw)

    agent_name = name
    if not agent_name:
        m = re.search(r"(?:called|named)\s+([A-Za-z][\w]*)", raw, re.IGNORECASE)
        if m:
            agent_name = m.group(1)
        else:
            m = re.search(r"(?:build|create|make)\s+(?:an?\s+)?([\w ]+?)\s+agent", raw, re.IGNORECASE)
            if m:
                agent_name = slugify(m.group(1))
    agent_name = slugify(agent_name)

    action_list = []
    if actions:
        items = actions if isinstance(actions, (list, tuple)) else re.split(r"[,\s;]+", str(actions))
        action_list = [slugify(a) for a in items if slugify(a)]
    if not action_list:
        m = re.search(r"actions?\s*[:=]\s*([^\n.]+)", raw, re.IGNORECASE)
        if m:
            action_list = [slugify(a) for a in re.split(r"[,\s;]+", m.group(1)) if slugify(a)]
    if not action_list:
        verbs = re.findall(
            r"\b(search|track|alert|list|open|browse|note|remind|summarise|summarize|"
            r"report|watch|check|fetch|save|notify)\b", raw, re.IGNORECASE)
        action_list = [slugify(v) for v in verbs]
    if not action_list:
        action_list = ["search", "save", "list"]

    seen, uniq = set(), []
    for a in action_list:
        if a not in seen and a not in ("help", "status"):
            seen.add(a)
            uniq.append(a)
    uniq = uniq[:MAX_ACTIONS]

    desc = description or raw or f"{agent_name} agent"
    return {"name": agent_name, "description": desc[:400], "actions": uniq,
            "blocked_term": blocked, "spec": raw}


# ── Capability mapping ──────────────────────────────────────────────────────

def infer_handler(action: str) -> str:
    """Pick an existing, already-guarded capability for an action name."""
    a = action.lower()
    if any(k in a for k in ("search", "find", "research", "fetch", "lookup")):
        return "web_search"
    if any(k in a for k in ("open", "browse", "visit", "site", "watch")):
        return "browser"
    if any(k in a for k in ("alert", "notify", "remind", "message", "tell")):
        return "alerts"
    if any(k in a for k in ("report", "summar", "export")):
        return "report"
    return "store"


_HANDLER_DOCS = {
    "web_search": "runs a web search",
    "browser": "opens a site in a visible browser",
    "alerts": "sends an alert to your configured channels",
    "report": "writes a markdown report to reports/",
    "store": "saves/reads entries in a local JSON store",
}


# ── Code generation ────────────────────────────────────────────────────────

_HEADER = '''"""
{title} — generated by core/agent_builder.py
{description}

Actions: {action_list}

Generated agents are stdlib-only at import time, wrapped in safe_tool so they
cannot crash the session, and delegate to existing guarded capabilities.
Fill in the TODOs to specialise the behaviour.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from core.safe_run import guard, safe_tool

STORE_PATH = Path("memory") / "{name}.json"
REPORT_DIR = Path("reports")


def _load() -> list:
    try:
        if STORE_PATH.exists():
            data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _save(rows: list) -> None:
    try:
        STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STORE_PATH.write_text(json.dumps(rows[-500:], indent=2), encoding="utf-8")
    except Exception:
        pass


def _record(kind: str, payload: dict) -> dict:
    rows = _load()
    entry = {{"t": time.time(), "kind": kind, **payload}}
    rows.append(entry)
    _save(rows)
    return entry


def _web_search(query: str) -> str:
    from actions.web_search import web_search
    return web_search({{"query": query}}) or "No results."


def _open_site(url: str, player=None) -> str:
    from actions.browser_control import browser_control
    from core.visible import visible
    if url and not url.startswith("http"):
        url = "https://" + url
    return browser_control(parameters=visible({{"action": "go_to", "url": url}}),
                           player=player) or "Opened."


def _alert(title: str, body: str) -> str:
    from core.alerts import notify
    res = notify(title, body)
    return "Alert sent: " + ", ".join(res.get("results", {{}}))


def _report(title: str, body: str) -> str:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    path = REPORT_DIR / (f"{name}_" + stamp + ".md")
    path.write_text(f"# {{title}}\\n\\n{{body}}\\n", encoding="utf-8")
    return f"Report saved: {{path}}"

'''


_ACTION_BLOCK = '''
def _action_{action}(params: dict, player=None, speak=None) -> str:
    """{action} — {doc}."""
    text = str(params.get("query") or params.get("text") or params.get("url")
               or params.get("value") or "").strip()
    if not text:
        return "What should I {action}? Give me a query, text or URL."
    _record("{action}", {{"input": text}})
{body}
'''

_BODIES = {
    "web_search": '    return _web_search(text)',
    "browser": '    return _open_site(text, player)',
    "alerts": '    return _alert(f"{title}", text)',
    "report": '    return _report(f"{title}", text)',
    "store": ('    rows = _load()\n'
              '    return f"Saved. {{len(rows)}} entry/entries stored for {name}."'),
}


def render_agent(spec: dict) -> str:
    name = spec["name"]
    title = name.replace("_", " ").title()
    actions = spec["actions"] or ["search", "save", "list"]
    src = _HEADER.format(title=title, name=name,
                         description=spec["description"].replace('"""', "'''"),
                         action_list=", ".join(actions + ["list", "help"]))
    for action in actions:
        handler = infer_handler(action)
        body = _BODIES[handler].format(title=title, name=name)
        src += _ACTION_BLOCK.format(action=action, doc=_HANDLER_DOCS[handler], body=body)

    src += f'''

@safe_tool("{name}")
def {name}(parameters: dict, player=None, speak=None) -> str:
    params = parameters or {{}}
    action = str(params.get("action", "help")).lower().strip()

    if action in ("help", "status"):
        return ("{title}\\n"
                "  Actions: {{joined}}\\n"
                "{{docs}}")

    if action == "list":
        rows = _load()
        if not rows:
            return "Nothing stored yet for {name}."
        return f"{title} — {{len(rows)}} entries:\\n" + "\\n".join(
            f"  [{{r.get('kind')}}] {{str(r.get('input', ''))[:80]}}" for r in rows[-15:])
'''
    for action in actions:
        src += f'''
    if action == "{action}":
        return _action_{action}(params, player, speak)
'''
    src += f'''
    return f"Unknown action '{{action}}' for {name}. Try: {{joined}}."
'''
    docs = "\\n".join(f"  {a}: {_HANDLER_DOCS[infer_handler(a)]}" for a in actions)
    src = src.replace("{docs}", docs).replace("{joined}", ", ".join(actions + ["list", "help"]))
    return src


def render_tests(spec: dict) -> str:
    name = spec["name"]
    actions = spec["actions"] or ["search"]
    lines = [f'"""Offline tests for the generated {name} agent."""', "",
             "import pytest", "",
             f"from actions import {name} as mod", "", "",
             "@pytest.fixture",
             "def store(tmp_path, monkeypatch):",
             '    monkeypatch.setattr(mod, "STORE_PATH", tmp_path / "store.json")',
             '    monkeypatch.setattr(mod, "REPORT_DIR", tmp_path / "reports")',
             "    return tmp_path", "", "",
             "def test_help(store):",
             f'    assert "{name.replace("_", " ").title()}" in mod.{name}({{"action": "help"}})',
             "", "",
             "def test_unknown_action(store):",
             f'    assert "Unknown action" in mod.{name}({{"action": "zzz"}})', "", "",
             "def test_list_empty(store):",
             f'    assert "Nothing stored" in mod.{name}({{"action": "list"}})', ""]
    for a in actions:
        lines += ["", f"def test_{a}_needs_input(store):",
                  f'    out = mod.{name}({{"action": "{a}"}})',
                  '    assert "Give me" in out', ""]
    lines += ["", "def test_never_raises_on_bad_params(store):",
              f"    assert isinstance(mod.{name}(None), str)",
              f'    assert isinstance(mod.{name}({{"action": 123}}), str)', ""]
    return "\n".join(lines)


# ── Registry ───────────────────────────────────────────────────────────────

def load_registry(path=None) -> list:
    p = Path(path) if path else _base_dir() / REGISTRY
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _remember(entry: dict, path=None):
    p = Path(path) if path else _base_dir() / REGISTRY
    try:
        rows = load_registry(p)
        rows.append(entry)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rows[-100:], indent=2), encoding="utf-8")
    except Exception:
        pass


def compile_check(source: str) -> tuple[bool, str]:
    """Parse + compile generated source before it ever touches disk."""
    try:
        ast.parse(source)
        compile(source, "<generated>", "exec")
        return True, ""
    except SyntaxError as exc:
        return False, f"line {exc.lineno}: {exc.msg}"


def build_agent(spec: dict, dry_run: bool = True, base_dir=None,
                write_tests: bool = True) -> dict:
    base = Path(base_dir) if base_dir else _base_dir()
    if spec.get("blocked_term"):
        return {"ok": False, "error": f"I won't build that — '{spec['blocked_term']}' "
                                      "is offensive tooling, which is out of scope."}
    ok, resolved = validate_name(spec["name"], base / ACTIONS_DIR)
    if not ok:
        return {"ok": False, "error": resolved}
    spec = dict(spec, name=resolved)

    source = render_agent(spec)
    valid, err = compile_check(source)
    if not valid:
        return {"ok": False, "error": f"Generated code failed its syntax check ({err}). Nothing written."}

    tests = render_tests(spec)
    tvalid, terr = compile_check(tests)
    if not tvalid:
        return {"ok": False, "error": f"Generated tests failed syntax check ({terr}). Nothing written."}

    agent_path = base / ACTIONS_DIR / f"{resolved}.py"
    test_path = base / TESTS_DIR / f"test_{resolved}.py"

    if dry_run:
        return {"ok": True, "dry_run": True, "name": resolved,
                "actions": spec["actions"], "path": str(agent_path),
                "test_path": str(test_path), "source": source, "tests": tests}

    try:
        agent_path.parent.mkdir(parents=True, exist_ok=True)
        agent_path.write_text(source, encoding="utf-8")
        if write_tests:
            test_path.parent.mkdir(parents=True, exist_ok=True)
            test_path.write_text(tests, encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": f"Could not write the files: {exc}"}

    _remember({"name": resolved, "actions": spec["actions"],
               "description": spec["description"], "created": time.time(),
               "path": str(agent_path), "test_path": str(test_path)},
              base / REGISTRY)
    return {"ok": True, "dry_run": False, "name": resolved, "actions": spec["actions"],
            "path": str(agent_path), "test_path": str(test_path)}


def remove_agent(name: str, base_dir=None) -> dict:
    """Remove ONLY agents this builder created (registry-checked)."""
    base = Path(base_dir) if base_dir else _base_dir()
    rows = load_registry(base / REGISTRY)
    entry = next((r for r in rows if r.get("name") == name), None)
    if not entry:
        return {"ok": False, "error": f"'{name}' wasn't created by the builder — I won't delete it."}
    removed = []
    for key in ("path", "test_path"):
        p = Path(entry.get(key, ""))
        try:
            if p.exists():
                p.unlink()
                removed.append(str(p))
        except OSError as exc:
            return {"ok": False, "error": f"Could not remove {p}: {exc}"}
    rows = [r for r in rows if r.get("name") != name]
    try:
        (base / REGISTRY).write_text(json.dumps(rows, indent=2), encoding="utf-8")
    except Exception:
        pass
    return {"ok": True, "removed": removed}


# ── Dispatcher ──────────────────────────────────────────────────────────────

@safe_tool("agent_builder")
def agent_builder(parameters: dict, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "help")).lower().strip()

    if action in ("help", "status"):
        return ("🛠️ Agent Builder — describe an agent, get a working agent\n"
                "  preview — show the generated code without writing anything\n"
                "  build   — write actions/<name>.py + tests/test_<name>.py\n"
                "  list    — agents this builder created\n"
                "  remove  — delete a builder-created agent\n"
                "Example: build an agent called crypto_watch with actions search, track, alert\n"
                "Generated agents are crash-proof and delegate to existing capabilities.")

    if action == "list":
        rows = load_registry()
        if not rows:
            return "No agents built yet."
        return "🛠️ Built agents:\n" + "\n".join(
            f"  {r['name']} — {', '.join(r.get('actions', []))}" for r in rows)

    if action == "remove":
        name = slugify(params.get("name", ""))
        if not name:
            return "Which agent should I remove?"
        res = remove_agent(name)
        if not res["ok"]:
            return res["error"]
        return "🗑️ Removed:\n" + "\n".join(f"  {p}" for p in res["removed"])

    if action not in ("preview", "build", "create"):
        return f"Unknown builder action '{action}'. Try preview, build, list, remove."

    spec = parse_spec(params.get("spec", "") or params.get("description", ""),
                      params.get("name", ""), params.get("actions"),
                      params.get("description", ""))
    if not spec["actions"]:
        return "Tell me what the agent should do — e.g. 'actions: search, track, alert'."

    dry = action == "preview" or bool(params.get("dry_run"))
    res = build_agent(spec, dry_run=dry)
    if not res["ok"]:
        return res["error"]

    mapping = "\n".join(f"  {a} → {_HANDLER_DOCS[infer_handler(a)]}"
                        for a in res["actions"])
    if res["dry_run"]:
        return (f"️ Preview: {res['name']}\n{mapping}\n\n"
                f"Would write:\n  {res['path']}\n  {res['test_path']}\n\n"
                "Say 'build it' to write the files.\n\n"
                "```python\n" + res["source"][:3000] + "\n```")
    return (f"✅ Built {res['name']}\n{mapping}\n\n"
            f"Files:\n  {res['path']}\n  {res['test_path']}\n\n"
            "It's crash-proof and importable now. To use it by voice, add it to "
            "TOOL_DECLARATIONS in main.py (or call it from a plan).")
