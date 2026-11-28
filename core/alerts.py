"""
Alert delivery for JARVIS — push notifications where you'll actually see them
─────────────────────────────────────────────────────────────────────────────
One call fans an alert out to every channel you've enabled:

    notify("Flight price drop", "NBO→DXB now $380 (was $450)")

Channels
────────
  gmail     — via actions/gmail_agent.send_mail (needs Google connected)
  notion    — via actions/notion_agent.create_page (needs a Notion token)
  telegram  — via actions/telegram_bot.send_telegram_notification
  file      — always available: appends to logs/alerts.log
  console   — always available: prints + writes to the UI log

Config: config/alerts.json (copy config/alerts.example.json)
    {"channels": ["file", "console"], "email_to": "", "notion_parent": "",
     "min_level": "info"}

Every channel is isolated: one failing delivery never blocks the others and
never raises. Delivery history is kept in memory/alerts.json (bounded).
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from core.safe_run import guard, safe_tool

CONFIG_PATH = Path("config") / "alerts.json"
HISTORY_PATH = Path("memory") / "alerts.json"
LOG_PATH = Path("logs") / "alerts.log"

CHANNELS = ("gmail", "notion", "telegram", "file", "console")
LEVELS = {"info": 0, "warning": 1, "critical": 2}
MAX_HISTORY = 200


def load_config(path=None) -> dict:
    cfg = {"channels": ["file", "console"], "email_to": "",
           "notion_parent": "", "min_level": "info"}
    p = Path(path) if path else CONFIG_PATH
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update({k: v for k, v in data.items() if k in cfg})
    except Exception:
        pass
    if not isinstance(cfg.get("channels"), list):
        cfg["channels"] = ["file", "console"]
    return cfg


def save_config(cfg: dict, path=None) -> bool:
    p = Path(path) if path else CONFIG_PATH
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def normalize_channels(raw) -> list[str]:
    if raw is None:
        return []
    items = raw if isinstance(raw, (list, tuple)) else str(raw).replace(";", ",").split(",")
    out, seen = [], set()
    for c in items:
        k = str(c or "").strip().lower()
        k = {"email": "gmail", "mail": "gmail", "tg": "telegram",
             "log": "file", "ui": "console"}.get(k, k)
        if k in CHANNELS and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def level_ok(level: str, min_level: str) -> bool:
    return LEVELS.get(str(level).lower(), 0) >= LEVELS.get(str(min_level).lower(), 0)


def format_alert(title: str, body: str, level: str = "info",
                 now: float | None = None) -> str:
    now = time.time() if now is None else now
    stamp = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M")
    icon = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(str(level).lower(), "ℹ️")
    return f"{icon} {title}\n{body}\n— JARVIS · {stamp}"


# ── Channel senders (each isolated, each returns a status string) ───────────

def _send_file(text: str, path=None) -> str:
    p = Path(path) if path else LOG_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(text + "\n" + "-" * 40 + "\n")
    return f"written to {p}"


def _send_console(text: str, player=None) -> str:
    print(text)
    writer = getattr(player, "write_log", None)
    if callable(writer):
        guard(writer, text, label="alerts.console")
    return "shown"


def _send_gmail(text: str, title: str, to: str) -> str:
    if not to:
        return "skipped (no email_to configured)"
    from actions.gmail_agent import send_mail
    result = send_mail(to=to, subject=f"[JARVIS] {title}", body=text)
    return str(result or "sent")


def _send_notion(text: str, title: str, parent: str) -> str:
    from actions.notion_agent import create_page
    result = create_page(title=f"[JARVIS] {title}", content=text, parent_id=parent or "")
    return str(result or "created")


def _send_telegram(text: str) -> str:
    from actions.telegram_bot import send_telegram_notification
    result = send_telegram_notification(text)
    return str(result or "sent")


_SENDERS = {
    "file": lambda text, title, cfg, player: _send_file(text),
    "console": lambda text, title, cfg, player: _send_console(text, player),
    "gmail": lambda text, title, cfg, player: _send_gmail(text, title, cfg.get("email_to", "")),
    "notion": lambda text, title, cfg, player: _send_notion(text, title, cfg.get("notion_parent", "")),
    "telegram": lambda text, title, cfg, player: _send_telegram(text),
}


# ── History ────────────────────────────────────────────────────────────────

def load_history(path=None) -> list:
    p = Path(path) if path else HISTORY_PATH
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _append_history(entry: dict, path=None):
    p = Path(path) if path else HISTORY_PATH
    try:
        rows = load_history(p)
        rows.append(entry)
        rows = rows[-MAX_HISTORY:]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    except Exception:
        pass


# ── Public API ─────────────────────────────────────────────────────────────

def notify(title: str, body: str = "", channels=None, level: str = "info",
           player=None, config: dict | None = None, now: float | None = None) -> dict:
    """Fan an alert out to the configured channels. Never raises."""
    now = time.time() if now is None else now
    cfg = config or load_config()
    title = str(title or "JARVIS alert").strip()
    body = str(body or "").strip()

    wanted = normalize_channels(channels) or normalize_channels(cfg.get("channels"))
    if not wanted:
        wanted = ["file"]

    if not level_ok(level, cfg.get("min_level", "info")):
        return {"ok": True, "skipped": True, "reason": f"below min_level ({level})",
                "results": {}}

    text = format_alert(title, body, level, now)
    results = {}
    for ch in wanted:
        sender = _SENDERS.get(ch)
        if sender is None:
            results[ch] = "unknown channel"
            continue
        try:
            results[ch] = str(sender(text, title, cfg, player))
        except Exception as exc:
            results[ch] = f"failed: {type(exc).__name__}: {str(exc)[:110]}"

    ok = any(not str(v).startswith(("failed", "unknown")) for v in results.values())
    entry = {"t": now, "title": title, "body": body[:400], "level": level,
             "channels": wanted, "results": results, "ok": ok}
    _append_history(entry)
    return {"ok": ok, "skipped": False, "results": results, "text": text}


def channel_status(config: dict | None = None) -> dict:
    """Which channels look usable right now (no messages are sent)."""
    cfg = config or load_config()
    out = {}
    for ch in CHANNELS:
        if ch in ("file", "console"):
            out[ch] = {"ready": True, "note": "always available"}
        elif ch == "gmail":
            to = cfg.get("email_to", "")
            out[ch] = {"ready": bool(to), "note": f"to {to}" if to else "set email_to"}
        elif ch == "notion":
            ready = False
            try:
                from actions.notion_agent import is_configured
                ready = bool(is_configured())
            except Exception:
                pass
            out[ch] = {"ready": ready, "note": "token configured" if ready else "run notion setup"}
        elif ch == "telegram":
            ready = False
            try:
                from actions.telegram_bot import get_bot
                ready = get_bot() is not None
            except Exception:
                pass
            out[ch] = {"ready": ready, "note": "bot running" if ready else "start the telegram bot"}
    return out


@safe_tool("alerts_control")
def alerts_control(parameters: dict, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).lower().strip()
    cfg = load_config()

    if action in ("send", "test", "notify"):
        title = params.get("title") or "Test alert"
        body = params.get("body") or params.get("message") or "This is a JARVIS test alert."
        res = notify(title, body, params.get("channels"),
                     params.get("level", "info"), player)
        if res.get("skipped"):
            return f"Alert not sent: {res['reason']}."
        lines = [f"{'✅' if not str(v).startswith(('failed', 'unknown')) else '❌'} {k}: {v}"
                 for k, v in res["results"].items()]
        return f"🔔 Alert '{title}' delivery:\n" + "\n".join(lines)

    if action == "history":
        rows = load_history()
        if not rows:
            return "No alerts sent yet."
        limit = int(params.get("limit", 10))
        lines = []
        for r in rows[-max(1, limit):]:
            stamp = datetime.fromtimestamp(float(r.get("t", 0))).strftime("%m-%d %H:%M")
            chans = ",".join(r.get("channels", []))
            lines.append(f"  {stamp} [{'ok' if r.get('ok') else 'FAIL'}] {r.get('title')} → {chans}")
        return f"🔔 Recent alerts ({len(rows)} total):\n" + "\n".join(lines)

    if action == "channels":
        status = channel_status(cfg)
        enabled = normalize_channels(cfg.get("channels"))
        lines = [f"  {'✅' if v['ready'] else '⚪'} {k}"
                 f"{' [enabled]' if k in enabled else ''} — {v['note']}"
                 for k, v in status.items()]
        return "🔔 Alert channels:\n" + "\n".join(lines)

    if action in ("enable", "add"):
        wanted = normalize_channels(params.get("channels") or params.get("channel"))
        if not wanted:
            return f"Which channel? Options: {', '.join(CHANNELS)}."
        current = normalize_channels(cfg.get("channels"))
        merged = current + [c for c in wanted if c not in current]
        cfg["channels"] = merged
        if params.get("email_to"):
            cfg["email_to"] = str(params["email_to"]).strip()
        if params.get("notion_parent"):
            cfg["notion_parent"] = str(params["notion_parent"]).strip()
        save_config(cfg)
        return f"🔔 Enabled: {', '.join(merged)}"

    if action in ("disable", "remove"):
        wanted = normalize_channels(params.get("channels") or params.get("channel"))
        if not wanted:
            return f"Which channel? Options: {', '.join(CHANNELS)}."
        cfg["channels"] = [c for c in normalize_channels(cfg.get("channels")) if c not in wanted]
        save_config(cfg)
        return f"🔔 Now enabled: {', '.join(cfg['channels']) or '(none)'}"

    if action == "recipient":
        email = str(params.get("email_to") or params.get("email") or "").strip()
        if not email:
            return "Give me an email address for alert delivery."
        cfg["email_to"] = email
        if "gmail" not in normalize_channels(cfg.get("channels")):
            cfg["channels"] = normalize_channels(cfg.get("channels")) + ["gmail"]
        save_config(cfg)
        return f"🔔 Alerts will email {email}."

    if action == "level":
        lvl = str(params.get("min_level", "")).lower()
        if lvl not in LEVELS:
            return f"min_level must be one of {', '.join(LEVELS)}."
        cfg["min_level"] = lvl
        save_config(cfg)
        return f"🔔 Minimum alert level: {lvl}."

    enabled = normalize_channels(cfg.get("channels"))
    ready = [k for k, v in channel_status(cfg).items() if v["ready"]]
    return (f"🔔 Alerts\n  Enabled: {', '.join(enabled) or '(none)'}\n"
            f"  Ready: {', '.join(ready)}\n"
            f"  Email to: {cfg.get('email_to') or '(not set)'}\n"
            f"  Min level: {cfg.get('min_level', 'info')}\n"
            "Actions: send, history, channels, enable, disable, recipient, level")
