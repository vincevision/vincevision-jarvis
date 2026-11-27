"""
findings_agent.py — VINCEVISION pentest findings tracker
────────────────────────────────────────────────────────
Record, track, and summarize security findings from an authorized engagement.
Stdlib-only (sqlite3). Stored in ``memory/findings.db`` (gitignored — client
findings are confidential).

Actions: add / list / get / update / delete / summary
Severity: critical / high / medium / low / info
Status:   open / fixed / accepted
"""

import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


DB_PATH = _base_dir() / "memory" / "findings.db"

SEVERITIES = ("critical", "high", "medium", "low", "info")
SEV_RANK = {s: i for i, s in enumerate(SEVERITIES)}
STATUSES = ("open", "fixed", "accepted")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS findings(
               id          INTEGER PRIMARY KEY AUTOINCREMENT,
               ts          REAL NOT NULL,
               title       TEXT NOT NULL,
               severity    TEXT NOT NULL DEFAULT 'medium',
               cvss        REAL,
               target      TEXT NOT NULL DEFAULT '',
               description TEXT NOT NULL DEFAULT '',
               remediation TEXT NOT NULL DEFAULT '',
               status      TEXT NOT NULL DEFAULT 'open',
               evidence    TEXT NOT NULL DEFAULT ''
           )"""
    )
    return conn


def _row(r) -> dict:
    return {k: r[k] for k in r.keys()}


def add_finding(title, severity="medium", target="", description="",
                remediation="", cvss=None, evidence="") -> int:
    title = (title or "").strip()
    if not title:
        return 0
    severity = severity.lower().strip()
    if severity not in SEVERITIES:
        severity = "medium"
    try:
        with closing(_connect()) as conn:
            cur = conn.execute(
                "INSERT INTO findings(ts, title, severity, cvss, target, description, "
                "remediation, status, evidence) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)",
                (time.time(), title, severity, cvss, target, description, remediation, evidence),
            )
            conn.commit()
            return int(cur.lastrowid)
    except Exception as e:
        print(f"[Findings] ⚠️ add failed: {e}")
        return 0


def list_findings(severity="", status="", limit=100) -> list:
    try:
        with closing(_connect()) as conn:
            q = "SELECT * FROM findings"
            clauses, args = [], []
            if severity:
                clauses.append("severity = ?"); args.append(severity.lower())
            if status:
                clauses.append("status = ?"); args.append(status.lower())
            if clauses:
                q += " WHERE " + " AND ".join(clauses)
            q += " ORDER BY ts DESC LIMIT ?"
            args.append(max(1, limit))
            rows = [_row(r) for r in conn.execute(q, args).fetchall()]
            rows.sort(key=lambda f: SEV_RANK.get(f["severity"], 99))
            return rows
    except Exception:
        return []


def get_finding(fid: int):
    try:
        with closing(_connect()) as conn:
            r = conn.execute("SELECT * FROM findings WHERE id = ?", (fid,)).fetchone()
            return _row(r) if r else None
    except Exception:
        return None


def update_finding(fid: int, **fields) -> bool:
    allowed = {"title", "severity", "cvss", "target", "description",
               "remediation", "status", "evidence"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return False
    if "severity" in updates:
        updates["severity"] = str(updates["severity"]).lower()
        if updates["severity"] not in SEVERITIES:
            updates.pop("severity")
    if "status" in updates:
        updates["status"] = str(updates["status"]).lower()
        if updates["status"] not in STATUSES:
            updates.pop("status")
    if not updates:
        return False
    try:
        with closing(_connect()) as conn:
            sets = ", ".join(f"{k} = ?" for k in updates)
            cur = conn.execute(f"UPDATE findings SET {sets} WHERE id = ?",
                               (*updates.values(), fid))
            conn.commit()
            return cur.rowcount > 0
    except Exception:
        return False


def delete_finding(fid: int) -> bool:
    try:
        with closing(_connect()) as conn:
            cur = conn.execute("DELETE FROM findings WHERE id = ?", (fid,))
            conn.commit()
            return cur.rowcount > 0
    except Exception:
        return False


def summary() -> dict:
    counts = {s: 0 for s in SEVERITIES}
    open_count = 0
    try:
        with closing(_connect()) as conn:
            for r in conn.execute("SELECT severity, status FROM findings"):
                counts[r["severity"]] = counts.get(r["severity"], 0) + 1
                if r["status"] == "open":
                    open_count += 1
    except Exception:
        pass
    return {"by_severity": counts, "total": sum(counts.values()), "open": open_count}


def format_findings(findings: list) -> str:
    if not findings:
        return "No findings recorded, sir."
    icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵", "info": "⚪"}
    lines = []
    for f in findings:
        lines.append(f"{icon.get(f['severity'], '•')} #{f['id']} [{f['severity'].upper()}] "
                     f"{f['title']}  ({f['status']})"
                     + (f"  @ {f['target']}" if f.get("target") else ""))
    return "\n".join(lines)


def findings_agent(parameters: dict, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "list")).lower().strip()

    if action == "add":
        title = (params.get("title") or "").strip()
        if not title:
            return "What's the finding title, sir?"
        fid = add_finding(
            title, params.get("severity", "medium"), params.get("target", ""),
            params.get("description", ""), params.get("remediation", ""),
            params.get("cvss"), params.get("evidence", ""),
        )
        if fid:
            if speak: speak("Finding recorded, sir.")
            return f"✅ Finding #{fid} recorded."
        return "Couldn't record the finding, sir."

    if action == "list":
        return format_findings(list_findings(params.get("severity", ""),
                                             params.get("status", ""),
                                             int(params.get("limit", 100) or 100)))

    if action in ("get", "read", "show"):
        fid = params.get("id")
        if fid is None:
            return "Which finding ID, sir?"
        f = get_finding(int(fid))
        if not f:
            return f"No finding #{fid}, sir."
        return (f"#{f['id']} [{f['severity'].upper()}] {f['title']}  ({f['status']})\n"
                f"Target: {f['target'] or 'n/a'}\nCVSS: {f['cvss'] if f['cvss'] is not None else 'n/a'}\n\n"
                f"{f['description']}\n\nRemediation: {f['remediation'] or 'n/a'}")

    if action == "update":
        fid = params.get("id")
        if fid is None:
            return "Which finding ID should I update, sir?"
        ok = update_finding(int(fid), **{k: params.get(k) for k in
                          ("title", "severity", "cvss", "target", "description",
                           "remediation", "status", "evidence")})
        return f"✅ Finding #{fid} updated." if ok else f"Couldn't update finding #{fid}, sir."

    if action == "delete":
        fid = params.get("id")
        if fid is None:
            return "Which finding ID should I delete, sir?"
        return (f"✅ Finding #{fid} deleted." if delete_finding(int(fid))
                else f"No finding #{fid} to delete, sir.")

    if action == "summary":
        s = summary()
        c = s["by_severity"]
        if speak:
            speak(f"{s['total']} findings, {s['open']} still open, sir.")
        return (f"📊 {s['total']} findings ({s['open']} open)\n"
                f"  🔴 Critical: {c['critical']}   🟠 High: {c['high']}   "
                f"🟡 Medium: {c['medium']}\n  🔵 Low: {c['low']}   ⚪ Info: {c['info']}")

    return "❌ Unknown findings action. Try: add, list, get, update, delete, summary."
