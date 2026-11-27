"""
long_term_memory.py
───────────────────
VINCEVISION Brain 2.0 — persistent long-term memory.

Stdlib-only (sqlite3 + FTS5 when available). The database lives at
``memory/long_term.db`` which is gitignored, so memories never leave the
machine they were created on.

Two layers of API:

1. Brain 2.0 semantic store
   remember() / recall() / get_preferences() / recent() / learn_from_task()

2. Compatibility shim for the original ``memory.memory_manager`` API
   load_memory() / update_memory() / format_memory_for_prompt()
   so a fresh clone (where the private memory/ package is absent) still runs.
"""

import re
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


DB_PATH = _base_dir() / "memory" / "long_term.db"

MAX_PROMPT_CHARS = 1600
MAX_ITEM_CHARS = 220

_FTS_OK = None  # tri-state cache: None = untested, True/False afterwards


# ════════════════════════════════════════════════════════════════
# Storage plumbing
# ════════════════════════════════════════════════════════════════

def _connect() -> sqlite3.Connection:
    """Open a fresh connection (thread-safe: one connection per call)."""
    global _FTS_OK
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS memories(
               id         INTEGER PRIMARY KEY AUTOINCREMENT,
               ts         REAL    NOT NULL,
               kind       TEXT    NOT NULL DEFAULT 'fact',
               category   TEXT    NOT NULL DEFAULT 'notes',
               key        TEXT    NOT NULL DEFAULT '',
               text       TEXT    NOT NULL,
               tags       TEXT    NOT NULL DEFAULT '',
               source     TEXT    NOT NULL DEFAULT '',
               importance REAL    NOT NULL DEFAULT 0.5
           )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_kind ON memories(kind)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_cat_key ON memories(category, key)")

    if _FTS_OK is not False:
        try:
            conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(text, tags)")
            _FTS_OK = True
        except sqlite3.OperationalError:
            _FTS_OK = False
    return conn


def _fts_sync(conn: sqlite3.Connection, rowid: int, text: str, tags: str) -> None:
    if not _FTS_OK:
        return
    conn.execute("DELETE FROM memories_fts WHERE rowid = ?", (rowid,))
    conn.execute(
        "INSERT INTO memories_fts(rowid, text, tags) VALUES (?, ?, ?)",
        (rowid, text, tags),
    )


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id":         row["id"],
        "ts":         row["ts"],
        "kind":       row["kind"],
        "category":   row["category"],
        "key":        row["key"],
        "text":       row["text"],
        "tags":       row["tags"],
        "source":     row["source"],
        "importance": row["importance"],
    }


# ════════════════════════════════════════════════════════════════
# Brain 2.0 API
# ════════════════════════════════════════════════════════════════

def remember(
    text: str,
    kind: str = "fact",
    category: str = "notes",
    key: str = "",
    tags: str = "",
    source: str = "",
    importance: float = 0.5,
) -> int:
    """
    Store a memory. When ``key`` is given, an existing memory with the same
    (category, key) is updated instead of duplicated — ideal for preferences.
    Returns the row id (0 on failure).
    """
    text = (text or "").strip()
    if not text:
        return 0
    try:
        with closing(_connect()) as conn:
            rowid = 0
            if key:
                row = conn.execute(
                    "SELECT id FROM memories WHERE category = ? AND key = ?",
                    (category, key),
                ).fetchone()
                if row:
                    rowid = row["id"]
                    conn.execute(
                        "UPDATE memories SET ts=?, kind=?, text=?, tags=?, source=?, importance=? WHERE id=?",
                        (time.time(), kind, text, tags, source, importance, rowid),
                    )
            if not rowid:
                cur = conn.execute(
                    "INSERT INTO memories(ts, kind, category, key, text, tags, source, importance) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (time.time(), kind, category, key, text, tags, source, importance),
                )
                rowid = cur.lastrowid
            _fts_sync(conn, rowid, text, tags)
            conn.commit()
            return int(rowid)
    except Exception as e:
        print(f"[Memory] ⚠️ remember failed: {e}")
        return 0


def recall(query: str = "", limit: int = 5, kinds: list | None = None) -> list:
    """
    Search long-term memory. Uses FTS5 when available, LIKE otherwise.
    An empty query returns the most recent memories.
    """
    limit = max(1, min(int(limit or 5), 50))
    try:
        with closing(_connect()) as conn:
            words = re.findall(r"\w+", query or "", flags=re.UNICODE)
            rows = []
            if words and _FTS_OK:
                match = " OR ".join(f'"{w}"' for w in words[:12])
                try:
                    rows = conn.execute(
                        "SELECT m.* FROM memories_fts f JOIN memories m ON m.id = f.rowid "
                        "WHERE memories_fts MATCH ? ORDER BY bm25(memories_fts) LIMIT ?",
                        (match, limit * 3),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []
            if not rows and words:
                like = f"%{words[0]}%"
                rows = conn.execute(
                    "SELECT * FROM memories WHERE text LIKE ? OR tags LIKE ? "
                    "ORDER BY importance DESC, ts DESC LIMIT ?",
                    (like, like, limit * 3),
                ).fetchall()
            if not rows:
                rows = conn.execute(
                    "SELECT * FROM memories ORDER BY ts DESC LIMIT ?", (limit * 3,)
                ).fetchall()

            items = [_row_to_dict(r) for r in rows]
            if kinds:
                items = [i for i in items if i["kind"] in kinds]
            # de-dup, keep order
            seen, out = set(), []
            for i in items:
                if i["id"] not in seen:
                    seen.add(i["id"])
                    out.append(i)
            return out[:limit]
    except Exception as e:
        print(f"[Memory] ⚠️ recall failed: {e}")
        return []


def recent(limit: int = 5) -> list:
    try:
        with closing(_connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM memories ORDER BY ts DESC LIMIT ?", (max(1, limit),)
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
    except Exception:
        return []


def get_preferences(limit: int = 30) -> list:
    try:
        with closing(_connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM memories WHERE kind = 'preference' "
                "ORDER BY importance DESC, ts DESC LIMIT ?",
                (max(1, limit),),
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
    except Exception:
        return []


def remember_preference(key: str, value: str, category: str = "preferences") -> int:
    return remember(
        f"{key}: {value}", kind="preference", category=category,
        key=key, source="preference", importance=0.8,
    )


def learn_from_task(goal: str, steps: list, outcome: str, success: bool = True) -> int:
    """Compact record of an agent task so future plans can reuse experience."""
    n = len(steps or [])
    text = f"Task: {(goal or '')[:200]} | steps: {n} | outcome: {(outcome or '')[:300]}"
    return remember(
        text, kind="task", category="tasks",
        tags="task " + ("success" if success else "failure"),
        source="agent", importance=0.6 if success else 0.4,
    )


def format_for_prompt(items: list) -> str:
    """Render memories for injection into a system prompt (bounded size)."""
    if not items:
        return ""
    lines = ["[LONG-TERM MEMORY]"]
    used = len(lines[0])
    for i in items:
        text = (i.get("text") or "").strip().replace("\n", " ")
        if len(text) > MAX_ITEM_CHARS:
            text = text[:MAX_ITEM_CHARS] + "…"
        line = f"- ({i.get('kind', 'fact')}) {text}"
        if used + len(line) + 1 > MAX_PROMPT_CHARS:
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines) if len(lines) > 1 else ""


def stats() -> dict:
    try:
        with closing(_connect()) as conn:
            total = conn.execute("SELECT COUNT(*) c FROM memories").fetchone()["c"]
            by_kind = {
                r["kind"]: r["c"]
                for r in conn.execute("SELECT kind, COUNT(*) c FROM memories GROUP BY kind")
            }
            return {"total": total, "by_kind": by_kind, "fts": bool(_FTS_OK), "db": str(DB_PATH)}
    except Exception as e:
        return {"total": 0, "by_kind": {}, "fts": False, "error": str(e)}


# ════════════════════════════════════════════════════════════════
# Compatibility shim — original memory.memory_manager API
# ════════════════════════════════════════════════════════════════

def load_memory() -> dict:
    """Nested {category: {key: {"value": ..., "ts": ...}}} like the original."""
    out: dict = {}
    try:
        with closing(_connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM memories WHERE key != '' ORDER BY category, key"
            ).fetchall()
            for r in rows:
                out.setdefault(r["category"], {})[r["key"]] = {
                    "value": r["text"], "ts": r["ts"],
                }
    except Exception as e:
        print(f"[Memory] ⚠️ load_memory failed: {e}")
    return out


def update_memory(updates: dict) -> None:
    """Merge {category: {key: {"value": v}}} (or plain values) into the store."""
    if not isinstance(updates, dict):
        return
    for category, keys in updates.items():
        if not isinstance(keys, dict):
            continue
        for key, val in keys.items():
            value = val.get("value") if isinstance(val, dict) else val
            if value is None or str(value).strip() == "":
                continue
            remember(
                str(value), kind="preference", category=str(category),
                key=str(key), source="compat", importance=0.7,
            )


def format_memory_for_prompt(memory: dict) -> str:
    """Render the nested compat structure for a system prompt (bounded)."""
    if not memory:
        return ""
    lines = ["[MEMORY]"]
    used = len(lines[0])
    for category, keys in memory.items():
        if not isinstance(keys, dict):
            continue
        for key, val in keys.items():
            value = val.get("value") if isinstance(val, dict) else val
            line = f"- {category}/{key}: {value}"
            if len(line) > MAX_ITEM_CHARS:
                line = line[:MAX_ITEM_CHARS] + "…"
            if used + len(line) + 1 > MAX_PROMPT_CHARS:
                return "\n".join(lines)
            lines.append(line)
            used += len(line) + 1
    return "\n".join(lines) if len(lines) > 1 else ""
