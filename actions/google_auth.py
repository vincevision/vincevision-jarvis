"""
google_auth.py — VINCEVISION shared Google OAuth helper
────────────────────────────────────────────────────────
One OAuth consent covers Gmail, Calendar, Docs and Drive. The Google SDKs
are imported lazily so the offline test suite (and CI) need nothing extra.

Files (all gitignored):
  config/google_client_secret.json   ← OAuth client secret you download once
  config/.credentials/google_token.json  ← refreshed access/refresh token

Run any Google agent's `setup` action for step-by-step instructions.
"""

import sys
from pathlib import Path


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


CONFIG_DIR = _base_dir() / "config"
CREDENTIALS_DIR = CONFIG_DIR / ".credentials"
CLIENT_SECRET_PATH = CONFIG_DIR / "google_client_secret.json"
TOKEN_PATH = CREDENTIALS_DIR / "google_token.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
]


def setup_instructions() -> str:
    return (
        "Connect Google in 4 steps, sir:\n"
        "  1. Go to https://console.cloud.google.com/ and create a project.\n"
        "  2. Enable the Gmail, Google Calendar, Google Docs and Google Drive APIs.\n"
        "  3. Create an OAuth client ID (Desktop app) and download the JSON.\n"
        "  4. Save it as config/google_client_secret.json, then say "
        "'connect google' — a browser window will ask you to approve access.\n"
        "Your token is stored locally in config/.credentials/ and never committed."
    )


def is_configured() -> bool:
    """True once the OAuth client secret file is present."""
    return CLIENT_SECRET_PATH.exists()


def has_token() -> bool:
    return TOKEN_PATH.exists()


def _save_token(creds) -> None:
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")


def get_credentials():
    """Load/refresh cached credentials, or run the consent flow once.

    Raises RuntimeError with setup instructions if the client secret is
    missing. Imports the Google SDKs lazily.
    """
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    creds = None
    if TOKEN_PATH.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        except Exception:
            creds = None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds)
        except Exception:
            creds = None

    if not creds or not creds.valid:
        if not is_configured():
            raise RuntimeError(setup_instructions())
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
        creds = flow.run_local_server(port=0)
        _save_token(creds)

    return creds


def get_service(api: str, version: str):
    """Build an authenticated Google API client (lazy import)."""
    from googleapiclient.discovery import build
    return build(api, version, credentials=get_credentials(), cache_discovery=False)


def status() -> str:
    if not is_configured():
        return "Google is not connected yet, sir. " + setup_instructions()
    if not has_token():
        return ("Google client secret found, but no token yet. "
                "Say 'connect google' to approve access.")
    return "✅ Google is connected (Gmail, Calendar, Docs, Drive)."


def logout() -> str:
    try:
        if TOKEN_PATH.exists():
            TOKEN_PATH.unlink()
            return "✅ Google token removed. You'll need to reconnect to use cloud tools."
        return "No Google token to remove, sir."
    except Exception as e:
        return f"Couldn't remove the Google token: {e}"


def google_auth_agent(parameters: dict, player=None, speak=None) -> str:
    """Voice entry point: connect / status / logout / setup."""
    params = parameters or {}
    action = str(params.get("action", "status")).lower().strip()

    if action in ("setup", "help", "instructions"):
        return setup_instructions()
    if action == "status":
        return status()
    if action in ("logout", "disconnect", "remove"):
        return logout()
    if action in ("connect", "login", "authorize", "auth"):
        try:
            get_credentials()
            return "✅ Google connected, sir. Gmail, Calendar, Docs and Drive are ready."
        except Exception as e:
            return f"Google connection failed: {e}"
    return "Say 'connect google', 'google status', or 'google logout', sir."
