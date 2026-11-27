"""
notes_agent.py — VINCEVISION quick notes & knowledge capture
────────────────────────────────────────────────────────────
Save, search, and recall notes by voice. Stdlib-only (sqlite3 + FTS5 when
available). Notes live in ``memory/notes.db`` (gitignored) — private to the
machine. Complements the Brain 2.0 long-term memory.

Actions: add / search / list / read / update / delete
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


DB_PATH = _base_dir() / "memory" / "notes.db"
_FTS_OK = None


def _connect() -> sqlite3.Connection:
    global _FTS_OK
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS notes(
               id    INTEGER PRIMARY KEY AUTOINCREMENT,
               ts    REAL NOT NULL,
               title TEXT NOT NULL DEFAULT '',
               text  TEXT NOT NULL,
               tags  TEXT NOT NULL DEFAULT ''
           )"""
    )
    if _FTS_OK is not False:
        try:
            conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(text, title, tags)")
            _FTS_OK = True
        except sqlite3.OperationalError:
            _FTS_OK = False
    return conn


def _fts_sync(conn, rowid, text, title, tags):
    if not _FTS_OK:
        return
    conn.execute("DELETE FROM notes_fts WHERE rowid = ?", (rowid,))
    conn.execute("INSERT INTO notes_fts(rowid, text, title, tags) VALUES (?, ?, ?, ?)",
                 (rowid, text, title, tags))


def _row(r) -> dict:
    return {"id": r["id"], "ts": r["ts"], "title": r["title"], "text": r["text"], "tags": r["tags"]}


# ── CRUD ────────────────────────────────────────────────────────

def add_note(text: str, title: str = "", tags: str = "") -> int:
    text = (text or "").strip()
    if not text:
        return 0
    try:
        with closing(_connect()) as conn:
            cur = conn.execute(
                "INSERT INTO notes(ts, title, text, tags) VALUES (?, ?, ?, ?)",
                (time.time(), title.strip(), text, tags.strip()),
            )
            rid = cur.lastrowid
            _fts_sync(conn, rid, text, title, tags)
            conn.commit()
            return int(rid)
    except Exception as e:
        print(f"[Notes] ⚠️ add failed: {e}")
        return 0


def search_notes(query: str, limit: int = 10) -> list:
    limit = max(1, min(int(limit or 10), 50))
    try:
        with closing(_connect()) as conn:
            words = re.findall(r"\w+", query or "", flags=re.UNICODE)
            rows = []
            if words and _FTS_OK:
                match = " OR ".join(f'"{w}"' for w in words[:12])
                try:
                    rows = conn.execute(
                        "SELECT n.* FROM notes_fts f JOIN notes n ON n.id = f.rowid "
                        "WHERE notes_fts MATCH ? ORDER BY bm25(notes_fts) LIMIT ?",
                        (match, limit),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []
            if not rows and words:
                like = f"%{words[0]}%"
                rows = conn.execute(
                    "SELECT * FROM notes WHERE text LIKE ? OR title LIKE ? OR tags LIKE ? "
                    "ORDER BY ts DESC LIMIT ?", (like, like, like, limit),
                ).fetchall()
            if not rows:
                rows = conn.execute("SELECT * FROM notes ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
            return [_row(r) for r in rows]
    except Exception as e:
        print(f"[Notes] ⚠️ search failed: {e}")
        return []


def list_notes(limit: int = 20, tag: str = "") -> list:
    try:
        with closing(_connect()) as conn:
            if tag:
                rows = conn.execute(
                    "SELECT * FROM notes WHERE tags LIKE ? ORDER BY ts DESC LIMIT ?",
                    (f"%{tag}%", max(1, limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM notes ORDER BY ts DESC LIMIT ?", (max(1, limit),)
                ).fetchall()
            return [_row(r) for r in rows]
    except Exception:
        return []


def get_note(note_id: int):
    try:
        with closing(_connect()) as conn:
            r = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
            return _row(r) if r else None
    except Exception:
        return None


def delete_note(note_id: int) -> bool:
    try:
        with closing(_connect()) as conn:
            cur = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            if _FTS_OK:
                conn.execute("DELETE FROM notes_fts WHERE rowid = ?", (note_id,))
            conn.commit()
            return cur.rowcount > 0
    except Exception:
        return False


def update_note(note_id: int, text=None, title=None, tags=None) -> bool:
    note = get_note(note_id)
    if not note:
        return False
    new_text = note["text"] if text is None else str(text).strip()
    new_title = note["title"] if title is None else str(title).strip()
    new_tags = note["tags"] if tags is None else str(tags).strip()
    if not new_text:
        return False
    try:
        with closing(_connect()) as conn:
            conn.execute("UPDATE notes SET text=?, title=?, tags=?, ts=? WHERE id=?",
                         (new_text, new_title, new_tags, time.time(), note_id))
            _fts_sync(conn, note_id, new_text, new_title, new_tags)
            conn.commit()
            return True
    except Exception:
        return False


def format_notes(notes: list, max_body: int = 160) -> str:
    if not notes:
        return "No notes found, sir."
    lines = []
    for n in notes:
        title = n.get("title") or "(untitled)"
        body = (n.get("text") or "").strip().replace("\n", " ")
        if len(body) > max_body:
            body = body[:max_body] + "…"
        tags = f"  [{n['tags']}]" if n.get("tags") else ""
        lines.append(f"#{n['id']} · {title}{tags}\n   {body}")
    return "\n".join(lines)


# ── Entry point ─────────────────────────────────────────────────

def notes_agent(parameters: dict, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "list")).lower().strip()

    if action in ("add", "save", "note", "create", "remember"):
        text = (params.get("text") or params.get("content") or params.get("body") or "").strip()
        if not text:
            return "What should I note down, sir?"
        nid = add_note(text, params.get("title", ""), params.get("tags", ""))
        if nid:
            if speak: speak("Noted, sir.")
            return f"✅ Note #{nid} saved."
        return "Couldn't save the note, sir."

    if action in ("search", "find", "recall"):
        query = (params.get("query") or params.get("keyword") or params.get("text") or "").strip()
        if not query:
            return "What should I search your notes for, sir?"
        results = search_notes(query, int(params.get("limit", 10) or 10))
        if speak: speak(f"Found {len(results)} note{'s' if len(results) != 1 else ''}, sir.")
        return format_notes(results)

    if action in ("list", "ls", "all"):
        results = list_notes(int(params.get("limit", 20) or 20), params.get("tag", ""))
        return format_notes(results)

    if action in ("read", "get", "open", "show"):
        nid = params.get("id") or params.get("note_id")
        if nid is None:
            return "Which note ID, sir?"
        note = get_note(int(nid))
        if not note:
            return f"No note #{nid}, sir."
        title = note["title"] or "(untitled)"
        return f"#{note['id']} · {title}\n\n{note['text']}"

    if action in ("update", "edit"):
        nid = params.get("id") or params.get("note_id")
        if nid is None:
            return "Which note ID should I edit, sir?"
        ok = update_note(int(nid), params.get("text"), params.get("title"), params.get("tags"))
        return f"✅ Note #{nid} updated." if ok else f"Couldn't update note #{nid}, sir."

    if action in ("delete", "remove", "forget"):
        nid = params.get("id") or params.get("note_id")
        if nid is None:
            return "Which note ID should I delete, sir?"
        ok = delete_note(int(nid))
        if ok and speak: speak("Note deleted, sir.")
        return f"✅ Note #{nid} deleted." if ok else f"No note #{nid} to delete, sir."

    return ("❌ Unknown notes action. Try: add, search, list, read, update, delete.")
