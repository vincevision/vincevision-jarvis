"""
drive_agent.py — VINCEVISION Google Drive
──────────────────────────────────────────
List, search, upload and download files. Uploads use the drive.file scope,
so JARVIS only touches files it created or you explicitly open with it.

Actions: list / search / upload / download / setup / status
"""

import mimetypes
from pathlib import Path

from actions import google_auth


def _service():
    return google_auth.get_service("drive", "v3")


def _fmt_file(f: dict) -> str:
    size = f.get("size")
    size_s = f" ({int(size)} bytes)" if size else ""
    return f"  • {f.get('name', '?')}{size_s} — id {f.get('id', '?')}"


def upload_file(path: str, name: str = "", folder_id: str = "") -> str:
    p = Path(path).expanduser()
    if not p.exists():
        return f"That file doesn't exist, sir: {p}"
    from googleapiclient.http import MediaFileUpload
    service = _service()
    mime = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
    media = MediaFileUpload(str(p), mimetype=mime, resumable=True)
    body = {"name": name or p.name}
    if folder_id:
        body["parents"] = [folder_id]
    f = service.files().create(body=body, media_body=media,
                               fields="id,name,webViewLink").execute()
    link = f.get("webViewLink", "")
    return f"✅ Uploaded '{f.get('name', p.name)}' to Drive." + (f" {link}" if link else "")


def download_file(file_id: str, dest: str = "") -> str:
    from googleapiclient.http import MediaIoBaseDownload
    import io
    service = _service()
    meta = service.files().get(fileId=file_id, fields="name").execute()
    name = meta.get("name", file_id)
    target = Path(dest).expanduser() if dest else Path.cwd() / name
    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(buf.getvalue())
    return f"✅ Downloaded '{name}' to {target}."


def drive_agent(parameters: dict, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "list")).lower().strip()

    if action in ("setup", "help", "connect"):
        return google_auth.setup_instructions()
    if action == "status":
        return google_auth.status()

    try:
        service = _service()

        if action in ("list", "ls", "recent"):
            res = service.files().list(
                pageSize=int(params.get("limit", 15)),
                orderBy="modifiedTime desc",
                fields="files(id,name,size,mimeType)").execute()
            files = res.get("files", [])
            return "🗂️ DRIVE\n" + ("\n".join(_fmt_file(f) for f in files)
                                   if files else "No files found, sir.")

        if action in ("search", "find"):
            q = params.get("query") or params.get("name") or ""
            if not q:
                return "What filename should I search for, sir?"
            safe = q.replace("'", "\\'")
            res = service.files().list(
                q=f"name contains '{safe}'",
                pageSize=int(params.get("limit", 15)),
                fields="files(id,name,size)").execute()
            files = res.get("files", [])
            return ("\n".join(_fmt_file(f) for f in files)
                    if files else f"No Drive files matching '{q}', sir.")

        if action in ("upload", "put"):
            path = params.get("path") or params.get("file") or ""
            if not path:
                return "Which file should I upload, sir? Provide a path."
            return upload_file(path, params.get("name", ""),
                               params.get("folder_id", ""))

        if action in ("download", "get"):
            fid = params.get("id") or params.get("file_id")
            if not fid:
                return "Which file id should I download, sir?"
            return download_file(fid, params.get("dest", ""))

        return "Drive actions: list, search, upload, download, setup."
    except Exception as e:
        return f"Drive request failed: {e}"
