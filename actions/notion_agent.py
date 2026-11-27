"""
notion_agent.py — VINCEVISION Notion workspace bridge
──────────────────────────────────────────────────────
Search, create pages, append blocks, and sync pentest findings into Notion.
Uses an internal integration token (no OAuth dance). Config lives in
config/notion_config.json (gitignored):

  { "token": "ntn_...", "parent_page_id": "...", "database_id": "..." }

Actions: setup / status / search / create_page / append / sync_findings
"""

import json
import sys
from pathlib import Path

import requests


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


CONFIG_PATH = _base_dir() / "config" / "notion_config.json"
API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
MAX_TEXT = 1900  # Notion rich_text block limit is 2000; stay safely under


def setup_instructions() -> str:
    return (
        "Connect Notion in 3 steps, sir:\n"
        "  1. Go to https://www.notion.so/my-integrations and create an internal "
        "integration; copy its token.\n"
        "  2. Open the Notion page (or database) you want JARVIS to use, click "
        "••• → Connections, and add your integration.\n"
        "  3. Say 'notion setup' with the token and the page id. "
        "Config is stored locally in config/notion_config.json and never committed."
    )


def _load_config() -> dict:
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"[Notion] ⚠️ config load failed: {e}")
    return {}


def _save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def is_configured() -> bool:
    return bool(_load_config().get("token"))


def _request(method: str, path: str, payload: dict | None = None) -> dict:
    """Thin Notion REST wrapper. Raises RuntimeError when unconfigured."""
    cfg = _load_config()
    token = cfg.get("token", "")
    if not token:
        raise RuntimeError(setup_instructions())
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    resp = requests.request(method, f"{API_BASE}{path}", headers=headers,
                            json=payload, timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(f"Notion API {resp.status_code}: {resp.text[:300]}")
    return resp.json() if resp.content else {}


def _text_blocks(text: str) -> list:
    """Split text into Notion paragraph blocks under the 2000-char limit."""
    blocks = []
    for chunk_start in range(0, max(1, len(text)), MAX_TEXT):
        chunk = text[chunk_start:chunk_start + MAX_TEXT]
        if not chunk:
            continue
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]},
        })
    return blocks or _text_blocks(" ")


def create_page(title: str, content: str = "", parent_id: str = "") -> str:
    cfg = _load_config()
    parent = parent_id or cfg.get("parent_page_id", "")
    if not parent:
        return ("I need a parent page id, sir. Set it with 'notion setup' "
                "or pass parent_id.")
    payload = {
        "parent": {"page_id": parent},
        "properties": {"title": [{"type": "text", "text": {"content": title or "Untitled"}}]},
        "children": _text_blocks(content) if content else [],
    }
    page = _request("POST", "/pages", payload)
    url = page.get("url", "")
    return f"✅ Notion page '{title}' created." + (f" {url}" if url else "")


def append_blocks(page_id: str, text: str) -> str:
    _request("PATCH", f"/blocks/{page_id}/children", {"children": _text_blocks(text)})
    return f"✅ Appended to Notion page {page_id}."


def search(query: str) -> str:
    res = _request("POST", "/search", {"query": query, "page_size": 10})
    results = res.get("results", [])
    if not results:
        return f"Nothing in Notion matching '{query}', sir."
    lines = []
    for r in results:
        title = ""
        props = r.get("properties", {})
        for p in props.values():
            if p.get("type") == "title":
                title = "".join(t.get("plain_text", "") for t in p.get("title", []))
                break
        lines.append(f"  • {title or r.get('object', 'item')} — id {r.get('id', '?')}")
    return "\n".join(lines)


def sync_findings(database_id: str = "") -> str:
    """Push current pentest findings into Notion.

    If a database_id is configured, each finding becomes a row (Name, Severity,
    CVSS, Target, Status). Otherwise a summary page is created under the parent.
    """
    from actions.findings_agent import list_findings, summary
    findings = list_findings(limit=1000)
    if not findings:
        return "No findings to sync, sir."
    cfg = _load_config()
    db = database_id or cfg.get("database_id", "")

    if db:
        created = 0
        for f in findings:
            props = {
                "Name": {"title": [{"text": {"content": f.get("title", "Finding")[:200]}}]},
                "Severity": {"select": {"name": f.get("severity", "info").capitalize()}},
                "Status": {"select": {"name": f.get("status", "open").capitalize()}},
            }
            if f.get("target"):
                props["Target"] = {"rich_text": [{"text": {"content": f["target"][:200]}}]}
            if f.get("cvss") is not None:
                props["CVSS"] = {"number": float(f["cvss"])}
            _request("POST", "/pages", {"parent": {"database_id": db}, "properties": props})
            created += 1
        return f"✅ Synced {created} findings to the Notion database."

    s = summary()
    lines = [f"# Pentest Findings — {s.get('total', len(findings))} total, "
             f"{s.get('open', 0)} open", ""]
    for f in findings:
        lines.append(f"## [{f.get('severity', '?').upper()}] {f.get('title', '')}")
        if f.get("target"):
            lines.append(f"Target: {f['target']}")
        if f.get("cvss") is not None:
            lines.append(f"CVSS: {f['cvss']}")
        if f.get("description"):
            lines.append(f["description"])
        if f.get("remediation"):
            lines.append(f"Remediation: {f['remediation']}")
        lines.append(f"Status: {f.get('status', 'open')}")
        lines.append("")
    return create_page("Pentest Findings Sync", "\n".join(lines))


def notion_agent(parameters: dict, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).lower().strip()

    if action in ("help", "instructions"):
        return setup_instructions()

    if action in ("setup", "connect", "configure"):
        token = params.get("token") or params.get("api_key") or ""
        if not token:
            return setup_instructions()
        cfg = _load_config()
        cfg["token"] = token
        if params.get("parent_page_id") or params.get("parent_id"):
            cfg["parent_page_id"] = params.get("parent_page_id") or params.get("parent_id")
        if params.get("database_id"):
            cfg["database_id"] = params["database_id"]
        _save_config(cfg)
        return "✅ Notion connected, sir. Token saved locally."

    if action == "status":
        if not is_configured():
            return "Notion is not connected yet, sir. " + setup_instructions()
        cfg = _load_config()
        extras = []
        if cfg.get("parent_page_id"):
            extras.append("parent page set")
        if cfg.get("database_id"):
            extras.append("findings database set")
        return "✅ Notion connected" + (f" ({', '.join(extras)})." if extras else ".")

    try:
        if action in ("search", "find", "query"):
            q = params.get("query") or params.get("q") or ""
            if not q:
                return "What should I search for in Notion, sir?"
            return search(q)

        if action in ("create_page", "create", "page", "new"):
            title = params.get("title") or "Untitled"
            return create_page(title, params.get("content") or params.get("text", ""),
                               params.get("parent_id", ""))

        if action in ("append", "add", "write"):
            pid = params.get("id") or params.get("page_id")
            text = params.get("text") or params.get("content", "")
            if not pid or not text:
                return "I need a page id and text to append, sir."
            return append_blocks(pid, text)

        if action in ("sync_findings", "sync", "findings"):
            out = sync_findings(params.get("database_id", ""))
            if speak:
                speak("Findings synced to Notion, sir.")
            return out

        return "Notion actions: setup, status, search, create_page, append, sync_findings."
    except Exception as e:
        return f"Notion request failed: {e}"
