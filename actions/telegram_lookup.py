# actions/telegram_lookup.py
"""
Telegram Phone Number Lookup
─────────────────────────────
Uses Telegram's official API to:
  - Check if a number is registered on Telegram
  - Get real name, username, bio, profile photo
  - Last seen status, premium status
  - Download profile picture
"""

import os
import sys
import random
from pathlib  import Path
from datetime import datetime


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR     = _get_base_dir()
PHOTOS_DIR   = BASE_DIR / "reports" / "telegram_photos"
SESSION_DIR  = BASE_DIR / "config"  / "telegram_sessions"
PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
SESSION_DIR.mkdir(parents=True, exist_ok=True)


def _get_credential(service: str, key: str) -> str:
    try:
        from core.credential_manager import get_credential
        return get_credential(service, key) or ""
    except Exception:
        return ""


def _save_credential(service: str, key: str, value: str):
    try:
        from core.credential_manager import save_credential
        save_credential(service, key, value)
    except Exception as e:
        print(f"[TelegramLookup] Failed to save credential: {e}")


# ═════════════════════════════════════════════
# FIRST-TIME LOGIN
# ═════════════════════════════════════════════

def telegram_first_login(api_id: int = None, api_hash: str = None,
                         phone: str = None, interactive: bool = True) -> dict:
    """
    First-time login to Telegram — saves session string.
    Returns: {"success": bool, "session": str, "message": str}
    """
    try:
        from telethon.sync     import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        return {
            "success": False,
            "message": "Telethon not installed. Run: pip install telethon",
        }

    # Pull from credential manager if not provided
    api_id   = api_id   or _get_credential("telegram", "api_id")
    api_hash = api_hash or _get_credential("telegram", "api_hash")

    if not api_id or not api_hash:
        return {
            "success": False,
            "message": "Telegram api_id and api_hash not configured. Get them from https://my.telegram.org",
        }

    try:
        api_id = int(api_id)
    except ValueError:
        return {
            "success": False,
            "message": f"api_id must be an integer, got: {api_id}",
        }

    try:
        client = TelegramClient(StringSession(), api_id, api_hash)

        if interactive:
            # Interactive console login
            print("\n" + "=" * 60)
            print("📱 TELEGRAM FIRST-TIME LOGIN")
            print("=" * 60)
            print("You'll receive a code on your Telegram app.")
            print("Enter it when prompted.\n")

            client.start(phone=phone)
        else:
            # Non-interactive — caller must handle codes
            client.connect()
            if not client.is_user_authorized():
                return {
                    "success": False,
                    "message": "Not authorized. Run interactive login first.",
                }

        session_string = client.session.save()
        me = client.get_me()
        client.disconnect()

        # Save the session string
        _save_credential("telegram", "session_string", session_string)

        return {
            "success":     True,
            "session":     session_string,
            "username":    me.username,
            "first_name":  me.first_name,
            "phone":       me.phone,
            "message":     f"✅ Logged in as {me.first_name} (@{me.username})",
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Login failed: {e}",
        }


# ═════════════════════════════════════════════
# PHONE LOOKUP
# ═════════════════════════════════════════════

def telegram_lookup(phone: str, download_photo: bool = True) -> dict:
    """
    Look up a phone number on Telegram.
    Returns rich profile data if registered.
    """
    result = {
        "registered": False,
        "phone":      phone,
    }

    try:
        from telethon.sync                 import TelegramClient
        from telethon.sessions             import StringSession
        from telethon.tl.functions.contacts import (
            ImportContactsRequest, DeleteContactsRequest,
        )
        from telethon.tl.functions.users   import GetFullUserRequest
        from telethon.tl.types             import (
            InputPhoneContact, UserStatusOnline, UserStatusRecently,
            UserStatusLastWeek, UserStatusLastMonth, UserStatusOffline,
        )
    except ImportError:
        result["error"] = "Telethon not installed"
        return result

    api_id   = _get_credential("telegram", "api_id")
    api_hash = _get_credential("telegram", "api_hash")
    session  = _get_credential("telegram", "session_string")

    if not api_id or not api_hash:
        result["error"] = "Telegram API not configured. Run setup wizard."
        return result

    if not session:
        result["error"] = "No Telegram session. Run telegram_first_login() first."
        return result

    try:
        api_id = int(api_id)
    except ValueError:
        result["error"] = f"Invalid api_id: {api_id}"
        return result

    try:
        with TelegramClient(StringSession(session), api_id, api_hash) as client:
            # Add as temporary contact
            contact = InputPhoneContact(
                client_id  = random.randint(0, 9999999),
                phone      = phone,
                first_name = "Lookup",
                last_name  = "Trace",
            )

            try:
                imported = client(ImportContactsRequest([contact]))
            except Exception as e:
                result["error"] = f"Import failed: {e}"
                return result

            if not imported.users:
                result["registered"] = False
                result["message"]    = "Number not registered on Telegram (or has phone privacy enabled)"
                return result

            user = imported.users[0]

            # Pull full user info
            try:
                full = client(GetFullUserRequest(user))
                full_user = full.full_user
                bio = full_user.about or ""
            except Exception:
                full_user = None
                bio = ""

            # Last seen status
            status = user.status
            last_seen = "Unknown"
            if isinstance(status, UserStatusOnline):
                last_seen = "🟢 Online now"
            elif isinstance(status, UserStatusRecently):
                last_seen = "🟡 Recently"
            elif isinstance(status, UserStatusLastWeek):
                last_seen = "🟠 Within a week"
            elif isinstance(status, UserStatusLastMonth):
                last_seen = "🔴 Within a month"
            elif isinstance(status, UserStatusOffline):
                last_seen = f"⚫ Last seen: {status.was_online}"

            result.update({
                "registered":    True,
                "user_id":       user.id,
                "username":      user.username,
                "first_name":    user.first_name,
                "last_name":     user.last_name,
                "full_name":     f"{user.first_name or ''} {user.last_name or ''}".strip(),
                "bio":           bio,
                "phone":         user.phone,
                "is_premium":    getattr(user, "premium", False),
                "is_verified":   user.verified,
                "is_bot":        user.bot,
                "is_scam":       getattr(user, "scam", False),
                "is_fake":       getattr(user, "fake", False),
                "last_seen":     last_seen,
                "has_photo":     user.photo is not None,
            })

            # Download profile photo
            if download_photo and user.photo:
                try:
                    photo_path = PHOTOS_DIR / f"{user.id}_{int(datetime.now().timestamp())}.jpg"
                    client.download_profile_photo(user, file=str(photo_path))
                    result["photo_path"] = str(photo_path)
                except Exception as e:
                    result["photo_error"] = str(e)

            # Cleanup — delete the contact we just added
            try:
                client(DeleteContactsRequest(id=[user]))
            except Exception:
                pass

            return result

    except Exception as e:
        result["error"] = f"Lookup failed: {e}"
        return result


# ═════════════════════════════════════════════
# CHECK IF CONFIGURED
# ═════════════════════════════════════════════

def is_telegram_configured() -> dict:
    """Check what's configured."""
    return {
        "api_id":         bool(_get_credential("telegram", "api_id")),
        "api_hash":       bool(_get_credential("telegram", "api_hash")),
        "session_string": bool(_get_credential("telegram", "session_string")),
    }


def is_telegram_ready() -> bool:
    """True if everything is configured for lookups."""
    cfg = is_telegram_configured()
    return all(cfg.values())