"""
gmail_agent.py — VINCEVISION Gmail via the official Google API
───────────────────────────────────────────────────────────────
The reliable, headless email path (no browser window needed). Complements
the existing browser/IMAP email_agent — use this once Google is connected.

Actions: unread / list / search / read / send / labels / setup / status
Requires: config/google_client_secret.json + a one-time 'connect google'.
"""

import base64
from email.mime.text import MIMEText

from actions import google_auth


def _service():
    return google_auth.get_service("gmail", "v1")


def _headers(msg: dict) -> dict:
    out = {}
    for h in msg.get("payload", {}).get("headers", []):
        out[h.get("name", "").lower()] = h.get("value", "")
    return out


def _decode_body(payload: dict) -> str:
    """Best-effort plain-text extraction from a Gmail message payload."""
    if not payload:
        return ""
    data = payload.get("body", {}).get("data")
    parts = payload.get("parts") or []
    if parts:
        # prefer text/plain parts, then fall back to anything readable
        for part in parts:
            if part.get("mimeType") == "text/plain":
                text = _decode_body(part)
                if text:
                    return text
        for part in parts:
            text = _decode_body(part)
            if text:
                return text
        return ""
    if data:
        try:
            return base64.urlsafe_b64decode(data).decode("utf-8", "replace")
        except Exception:
            return ""
    return ""


def _fmt_list(messages: list, service) -> str:
    if not messages:
        return "No matching messages, sir."
    lines = []
    for m in messages[:15]:
        try:
            full = service.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["Subject", "From", "Date"]).execute()
            h = _headers(full)
            lines.append(f"  • {h.get('from', '?')} — {h.get('subject', '(no subject)')}")
        except Exception:
            lines.append(f"  • message {m.get('id', '?')}")
    return "\n".join(lines)


def send_mail(to: str, subject: str, body: str) -> str:
    service = _service()
    mime = MIMEText(body or "")
    mime["to"] = to
    mime["subject"] = subject or ""
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("utf-8")
    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return f"✅ Email sent to {to} (id {sent.get('id', '?')})."


def gmail_agent(parameters: dict, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "unread")).lower().strip()

    if action in ("setup", "help", "connect"):
        return google_auth.setup_instructions()
    if action == "status":
        return google_auth.status()

    try:
        service = _service()
    except Exception as e:
        return f"Gmail isn't ready, sir. {e}"

    try:
        if action in ("unread", "list", "inbox", "check"):
            q = "is:unread" if action == "unread" else params.get("query", "")
            res = service.users().messages().list(
                userId="me", q=q, maxResults=int(params.get("limit", 10))).execute()
            msgs = res.get("messages", [])
            out = _fmt_list(msgs, service)
            if action == "unread" and speak:
                speak(f"You have {len(msgs)} unread messages, sir.")
            return out

        if action == "search":
            q = params.get("query") or params.get("q") or ""
            if not q:
                return "What should I search for in your mail, sir?"
            res = service.users().messages().list(
                userId="me", q=q, maxResults=int(params.get("limit", 10))).execute()
            return _fmt_list(res.get("messages", []), service)

        if action in ("read", "open", "get"):
            mid = params.get("id") or params.get("message_id")
            if not mid:
                return "Which message id should I read, sir?"
            full = service.users().messages().get(userId="me", id=mid, format="full").execute()
            h = _headers(full)
            body = _decode_body(full.get("payload", {}))
            return (f"From: {h.get('from', '?')}\nSubject: {h.get('subject', '(none)')}\n"
                    f"Date: {h.get('date', '?')}\n\n{body[:4000]}")

        if action in ("send", "compose", "reply"):
            to = params.get("to") or params.get("recipient") or ""
            if not to:
                return "Who should I send it to, sir? Provide a 'to' address."
            return send_mail(to, params.get("subject", ""), params.get("body", ""))

        if action == "labels":
            res = service.users().labels().list(userId="me").execute()
            names = [l.get("name", "") for l in res.get("labels", [])]
            return "Labels: " + ", ".join(names) if names else "No labels found."

        return "Gmail actions: unread, list, search, read, send, labels, setup."
    except Exception as e:
        return f"Gmail request failed: {e}"
