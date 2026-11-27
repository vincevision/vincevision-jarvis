# social_login.py
"""
JARVIS Social Media Login Manager
───────────────────────────────────
Securely stores and manages social media credentials.
Uses them to auto-login when browser session fails.
"""

import json
import sys
import time
import asyncio
from pathlib import Path


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


# ─────────────────────────────────────────────
# CREDENTIAL STORAGE
# ─────────────────────────────────────────────

def _save_social_login(platform: str, username: str, password: str):
    """Save social media login securely."""
    from core.credential_manager import save_credential
    save_credential(f"social_{platform}", "username", username)
    save_credential(f"social_{platform}", "password", password)
    print(f"[SocialLogin] ✅ Saved {platform} credentials")


def _get_social_login(platform: str) -> dict | None:
    """Get saved social media login."""
    from core.credential_manager import get_credential
    username = get_credential(f"social_{platform}", "username")
    password = get_credential(f"social_{platform}", "password")
    if username and password:
        return {"username": username, "password": password}
    return None


def _ask_credentials(platform: str) -> dict | None:
    """Ask user for credentials via terminal (safe for root)."""
    import os
    import getpass

    print(f"\n[JARVIS] {platform.capitalize()} login required")
    print("─" * 40)

    try:
        username = input(f"  {platform.capitalize()} username/email: ").strip()
        if not username:
            return None
        password = getpass.getpass(f"  {platform.capitalize()} password: ").strip()
        if not password:
            return None
        return {"username": username, "password": password}
    except Exception:
        return None


# ─────────────────────────────────────────────
# AUTO LOGIN FUNCTIONS
# ─────────────────────────────────────────────

async def _login_instagram(sess, credentials: dict) -> bool:
    """Auto-login to Instagram."""
    try:
        await sess.go_to("https://www.instagram.com/accounts/login/")
        await asyncio.sleep(3)

        page = await sess._get_page()

        # Type username
        for sel in ['input[name="username"]', 'input[aria-label="Phone number, username, or email"]']:
            try:
                await page.fill(sel, credentials["username"])
                break
            except Exception:
                continue

        await asyncio.sleep(0.5)

        # Type password
        for sel in ['input[name="password"]', 'input[aria-label="Password"]']:
            try:
                await page.fill(sel, credentials["password"])
                break
            except Exception:
                continue

        await asyncio.sleep(0.5)

        # Click login
        for sel in ['button[type="submit"]', 'button:has-text("Log in")']:
            try:
                await page.click(sel, timeout=3000)
                break
            except Exception:
                continue

        await asyncio.sleep(4)

        # Check if logged in
        current_url = page.url
        if "login" not in current_url.lower():
            print("[SocialLogin] ✅ Instagram logged in!")
            return True

        # Handle 2FA or "Save info" prompt
        page_text = await page.inner_text("body")
        if "save" in page_text.lower() or "not now" in page_text.lower():
            try:
                await page.click('button:has-text("Not Now")', timeout=3000)
                await asyncio.sleep(2)
            except Exception:
                pass
            return True

        return False

    except Exception as e:
        print(f"[SocialLogin] Instagram login error: {e}")
        return False


async def _login_twitter(sess, credentials: dict) -> bool:
    """Auto-login to Twitter/X."""
    try:
        await sess.go_to("https://x.com/login")
        await asyncio.sleep(3)

        page = await sess._get_page()

        # Type username
        for sel in [
            'input[autocomplete="username"]',
            'input[name="text"]',
        ]:
            try:
                await page.fill(sel, credentials["username"])
                await page.keyboard.press("Enter")
                await asyncio.sleep(2)
                break
            except Exception:
                continue

        # Type password
        for sel in [
            'input[name="password"]',
            'input[type="password"]',
        ]:
            try:
                await page.fill(sel, credentials["password"])
                await page.keyboard.press("Enter")
                await asyncio.sleep(3)
                break
            except Exception:
                continue

        current_url = page.url
        if "home" in current_url or "x.com" in current_url and "login" not in current_url:
            print("[SocialLogin] ✅ Twitter logged in!")
            return True

        return False

    except Exception as e:
        print(f"[SocialLogin] Twitter login error: {e}")
        return False


async def _login_linkedin(sess, credentials: dict) -> bool:
    """Auto-login to LinkedIn."""
    try:
        await sess.go_to("https://www.linkedin.com/login")
        await asyncio.sleep(3)

        page = await sess._get_page()

        await page.fill('input[id="username"]', credentials["username"])
        await asyncio.sleep(0.3)
        await page.fill('input[id="password"]', credentials["password"])
        await asyncio.sleep(0.3)
        await page.click('button[type="submit"]')
        await asyncio.sleep(4)

        current_url = page.url
        if "feed" in current_url or "dashboard" in current_url:
            print("[SocialLogin] ✅ LinkedIn logged in!")
            return True

        return False

    except Exception as e:
        print(f"[SocialLogin] LinkedIn login error: {e}")
        return False


async def _login_facebook(sess, credentials: dict) -> bool:
    """Auto-login to Facebook."""
    try:
        await sess.go_to("https://www.facebook.com/login")
        await asyncio.sleep(3)

        page = await sess._get_page()

        await page.fill('input[id="email"]',    credentials["username"])
        await page.fill('input[id="pass"]',     credentials["password"])
        await page.click('button[name="login"]')
        await asyncio.sleep(4)

        current_url = page.url
        if "facebook.com" in current_url and "login" not in current_url:
            print("[SocialLogin] ✅ Facebook logged in!")
            return True

        return False

    except Exception as e:
        print(f"[SocialLogin] Facebook login error: {e}")
        return False


# Login function map
_LOGIN_FUNCTIONS = {
    "instagram": _login_instagram,
    "twitter":   _login_twitter,
    "x":         _login_twitter,
    "linkedin":  _login_linkedin,
    "facebook":  _login_facebook,
}


# ─────────────────────────────────────────────
# MAIN LOGIN HANDLER
# ─────────────────────────────────────────────

def ensure_logged_in(
    platform: str,
    browser:  str = "brave",
    player=None,
    speak=None,
    force: bool = False,
) -> dict:
    """
    Ensure user is logged in to a social platform.
    Returns status dict.
    """
    from actions.browser_control import _registry

    platform = platform.lower().strip()
    login_fn = _LOGIN_FUNCTIONS.get(platform)

    if not login_fn:
        return {
            "success": False,
            "message": f"Unknown platform: {platform}"
        }

    try:
        sess = _registry.get(browser)

        # Check if already logged in
        if not force:
            from actions.social_agent import _check_login_status
            status = sess.run(
                _check_login_status(sess, platform),
                timeout=15
            )
            if status.get("logged_in"):
                return {
                    "success": True,
                    "message": f"Already logged in to {platform}",
                    "method":  "existing_session"
                }

        print(f"[SocialLogin] Not logged in to {platform}. Attempting auto-login...")

        if player:
            player.write_log(f"[SocialLogin] Logging in to {platform}...")

        if speak:
            speak(f"Logging in to {platform}, sir.")

        # Get saved credentials
        creds = _get_social_login(platform)

        # If no saved creds ask user
        if not creds:
            if speak:
                speak(
                    f"I need your {platform} credentials, sir. "
                    "Please check the terminal."
                )

            creds = _ask_credentials(platform)

            if creds:
                # Ask if should save
                save = input(
                    f"  Save {platform} credentials for future use? (y/n): "
                ).strip().lower()
                if save == "y":
                    _save_social_login(
                        platform,
                        creds["username"],
                        creds["password"]
                    )
            else:
                return {
                    "success": False,
                    "message": "No credentials provided."
                }

        # Attempt login
        success = sess.run(
            login_fn(sess, creds),
            timeout=30
        )

        if success:
            msg = f"Successfully logged in to {platform}, sir."
            if speak:
                speak(msg)
            return {
                "success": True,
                "message": msg,
                "method":  "auto_login"
            }
        else:
            msg = (
                f"Auto-login to {platform} failed. "
                "Please log in manually in the browser."
            )
            if speak:
                speak(msg)
            return {
                "success": False,
                "message": msg
            }

    except Exception as e:
        return {
            "success": False,
            "message": f"Login error: {e}"
        }


def social_login_agent(
    parameters: dict,
    player=None,
    speak=None,
) -> str:
    """
    Social login agent entry point.
    """
    params   = parameters or {}
    action   = params.get("action",   "login").lower()
    platform = params.get("platform", "").lower()
    browser  = params.get("browser",  "brave").lower()
    force    = params.get("force",    False)

    if action == "save":
        username = params.get("username", "").strip()
        password = params.get("password", "").strip()
        if not platform:
            return "Please specify a platform."
        if not username or not password:
            creds = _ask_credentials(platform)
            if creds:
                _save_social_login(platform, creds["username"], creds["password"])
                return f"Credentials saved for {platform}."
            return "No credentials provided."
        _save_social_login(platform, username, password)
        return f"Credentials saved for {platform}."

    elif action == "login":
        if not platform:
            return "Please specify a platform."
        result = ensure_logged_in(platform, browser, player, speak, force)
        return result["message"]

    elif action == "clear":
        if not platform:
            return "Please specify a platform to clear."
        from core.credential_manager import delete_credential
        delete_credential(f"social_{platform}")
        return f"Credentials cleared for {platform}."

    elif action == "list":
        from core.credential_manager import list_credentials
        creds = list_credentials()
        social = {
            k.replace("social_", ""): v
            for k, v in creds.items()
            if k.startswith("social_")
        }
        if not social:
            return "No social media credentials saved."
        lines = ["Saved social media credentials:"]
        for platform_name, keys in social.items():
            lines.append(f"  • {platform_name}: {', '.join(keys)}")
        return "\n".join(lines)

    return f"Unknown action: {action}"