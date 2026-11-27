"""
docs_agent.py — VINCEVISION Google Docs
────────────────────────────────────────
Create, read and append to Google Docs — including one-command export of a
pentest report straight into a shareable Doc.

Actions: create / read / append / export_report / setup / status
"""

from actions import google_auth


def _service():
    return google_auth.get_service("docs", "v1")


def _doc_url(doc_id: str) -> str:
    return f"https://docs.google.com/document/d/{doc_id}/edit"


def extract_text(doc: dict) -> str:
    """Flatten a Docs API document body into plain text."""
    lines = []
    for block in doc.get("body", {}).get("content", []):
        para = block.get("paragraph")
        if not para:
            continue
        text = "".join(el.get("textRun", {}).get("content", "")
                       for el in para.get("elements", []))
        lines.append(text.rstrip("\n"))
    return "\n".join(lines)


def _end_index(doc: dict) -> int:
    content = doc.get("body", {}).get("content", [])
    if not content:
        return 1
    return max(1, content[-1].get("endIndex", 2) - 1)


def create_doc(title: str, text: str = "") -> str:
    service = _service()
    doc = service.documents().create(body={"title": title or "Untitled"}).execute()
    doc_id = doc.get("documentId", "")
    if text:
        service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": [{"insertText": {"location": {"index": 1}, "text": text}}]}
        ).execute()
    return f"✅ Doc '{title}' created: {_doc_url(doc_id)}"


def append_text(doc_id: str, text: str) -> str:
    service = _service()
    doc = service.documents().get(documentId=doc_id).execute()
    idx = _end_index(doc)
    service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": [{"insertText": {"location": {"index": idx}, "text": text}}]}
    ).execute()
    return f"✅ Appended {len(text)} characters to the doc."


def export_report(title: str = "", client: str = "") -> str:
    """Build the pentest report locally, then push it into a new Google Doc."""
    from actions.report_agent import build_report, _gather
    findings, scope = _gather()
    meta = {}
    if title:
        meta["title"] = title
    if client:
        meta["client"] = client
    text = build_report(findings, scope, meta)
    doc_title = title or (f"Pentest Report — {client}" if client else "Pentest Report")
    return create_doc(doc_title, text)


def docs_agent(parameters: dict, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "create")).lower().strip()

    if action in ("setup", "help", "connect"):
        return google_auth.setup_instructions()
    if action == "status":
        return google_auth.status()

    try:
        if action in ("create", "new"):
            title = params.get("title") or "Untitled"
            return create_doc(title, params.get("text", ""))

        if action in ("read", "get", "open"):
            doc_id = params.get("id") or params.get("document_id")
            if not doc_id:
                return "Which document id should I read, sir?"
            service = _service()
            doc = service.documents().get(documentId=doc_id).execute()
            title = doc.get("title", "Untitled")
            return f"📄 {title}\n\n{extract_text(doc)[:6000]}"

        if action in ("append", "add", "write"):
            doc_id = params.get("id") or params.get("document_id")
            text = params.get("text", "")
            if not doc_id or not text:
                return "I need a document id and some text to append, sir."
            return append_text(doc_id, text)

        if action in ("export_report", "report", "export"):
            out = export_report(params.get("title", ""), params.get("client", ""))
            if speak:
                speak("Pentest report exported to Google Docs, sir.")
            return out

        return "Docs actions: create, read, append, export_report, setup."
    except Exception as e:
        return f"Docs request failed: {e}"
