"""
social_browser.py — VINCEVISION browser-session login for social platforms
──────────────────────────────────────────────────────────────────────────
Same approach as the email agent: sign in to YOUR OWN account in a real
browser window using your normal username + password (and 2FA), then the
session is saved locally and reused. No stored passwords, no credential
typing, no "long process".

PRIVACY / SECURITY MODEL
  * You type your password directly into the platform's real login page.
    JARVIS NEVER reads, logs, stores, or transmits your password.
  * Only the browser's session profile (cookies) is persisted, under
    ``browser_profiles/social/<platform>/<account>/`` — gitignored, so it
    never leaves your machine and is never pushed to GitHub.
  * 2FA / captcha / checkpoints are completed by YOU in the visible window.

Supported: Instagram, Twitter/X, Facebook, LinkedIn, TikTok.
"""

import os
import re
import shutil
import sys
import time
from pathlib import Path


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


PROFILES_ROOT = _base_dir() / "browser_profiles" / "social"
LOGIN_TIMEOUT = 300


PLATFORMS = {
    "instagram": {
        "name": "Instagram",
        "login_url": "https://www.instagram.com/accounts/login/",
        "home_url": "https://www.instagram.com/",
    },
    "twitter": {
        "name": "X (Twitter)",
        "login_url": "https://x.com/i/flow/login",
        "home_url": "https://x.com/home",
    },
    "facebook": {
        "name": "Facebook",
        "login_url": "https://www.facebook.com/login",
        "home_url": "https://www.facebook.com/",
    },
    "linkedin": {
        "name": "LinkedIn",
        "login_url": "https://www.linkedin.com/login",
        "home_url": "https://www.linkedin.com/feed/",
    },
    "tiktok": {
        "name": "TikTok",
        "login_url": "https://www.tiktok.com/login",
        "home_url": "https://www.tiktok.com/",
    },
}

_ALIASES = {"x": "twitter", "insta": "instagram", "ig": "instagram",
            "fb": "facebook", "tik tok": "tiktok", "linked in": "linkedin"}


# ════════════════════════════════════════════════════════════════
# Pure helpers (unit-tested offline)
# ════════════════════════════════════════════════════════════════

def normalize_platform(name: str) -> str:
    val = (name or "").strip().lower()
    val = _ALIASES.get(val, val)
    return val if val in PLATFORMS else ""


def profile_dir(platform: str, account: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "_", (account or "default").lower()).strip("_") or "default"
    return PROFILES_ROOT / platform / slug


def is_logged_in_url(platform: str, url: str) -> bool:
    url = url or ""
    if platform == "instagram":
        return ("instagram.com" in url
                and not any(s in url for s in (
                    "/accounts/login", "/accounts/onetap", "/challenge",
                    "/accounts/registered", "/accounts/emailsignup")))
    if platform == "twitter":
        return "x.com/home" in url or "twitter.com/home" in url
    if platform == "facebook":
        return ("facebook.com" in url
                and not any(s in url for s in ("/login", "/checkpoint", "/recover")))
    if platform == "linkedin":
        return ("linkedin.com" in url
                and not any(s in url for s in ("/login", "/checkpoint", "/uas/login")))
    if platform == "tiktok":
        return "tiktok.com" in url and "/login" not in url
    return False


def connected_platforms() -> list:
    """Platforms that have at least one saved session profile."""
    out = []
    if PROFILES_ROOT.exists():
        for plat in PLATFORMS:
            pdir = PROFILES_ROOT / plat
            if pdir.exists() and any(pdir.iterdir()):
                out.append(plat)
    return out


def _log(player, msg):
    print(f"[SocialBrowser] {msg}")
    if player:
        try:
            player.write_log(f"[Social] {msg}"[:200])
        except Exception:
            pass


def _speak(speak, msg):
    if speak:
        try:
            speak(msg)
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════
# Playwright plumbing (lazy imports)
# ════════════════════════════════════════════════════════════════

def _launch_kwargs(headless: bool):
    args = ["--no-sandbox", "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled", "--start-maximized"]
    env = os.environ.copy()
    try:
        from actions.browser_control import _get_args, _build_env_for_user, _get_real_user
        user, uid = _get_real_user()
        args = _get_args(headless)
        env = _build_env_for_user(user, uid)
    except Exception:
        pass
    return args, env


def _launch_context(pw, pdir: Path, headless: bool):
    pdir.mkdir(parents=True, exist_ok=True)
    args, env = _launch_kwargs(headless)
    last_err = None
    for channel in ("chrome", "msedge", None):
        try:
            kw = dict(user_data_dir=str(pdir), headless=headless,
                      args=args, env=env, viewport=None, no_viewport=True)
            if channel:
                kw["channel"] = channel
            return pw.chromium.launch_persistent_context(**kw)
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Could not launch a browser: {last_err}")


def _first_page(ctx):
    return ctx.pages[0] if ctx.pages else ctx.new_page()


def _goto(page, url, timeout=60000):
    page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    page.wait_for_timeout(2000)


# ════════════════════════════════════════════════════════════════
# Actions
# ════════════════════════════════════════════════════════════════

def _do_login(platform: str, account: str, player, speak) -> bool:
    spec = PLATFORMS[platform]
    pdir = profile_dir(platform, account)
    from playwright.sync_api import sync_playwright

    _log(player, f"Opening {spec['name']} login window…")
    _speak(speak,
           f"Opening {spec['name']}. Please sign in with your normal username and password. "
           "I never see your password — complete any two-step prompt yourself.")
    try:
        with sync_playwright() as pw:
            ctx = _launch_context(pw, pdir, headless=False)
            page = _first_page(ctx)
            try:
                _goto(page, spec["login_url"])
            except Exception as e:
                ctx.close()
                _log(player, f"Couldn't open login page: {e}")
                return False
            deadline = time.time() + LOGIN_TIMEOUT
            ok = False
            while time.time() < deadline:
                try:
                    if is_logged_in_url(platform, page.url):
                        page.wait_for_timeout(2500)
                        if is_logged_in_url(platform, page.url):
                            ok = True
                            break
                except Exception:
                    break  # window closed
                time.sleep(2)
            ctx.close()
    except Exception as e:
        _log(player, f"Browser login failed: {e}")
        return False

    if ok:
        _log(player, f"{spec['name']} session saved.")
        _speak(speak, f"{spec['name']} is connected, sir. Your session is saved.")
    return ok


def _check_status(platform: str, account: str) -> bool:
    pdir = profile_dir(platform, account)
    if not pdir.exists():
        return False
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx = _launch_context(pw, pdir, headless=True)
        page = _first_page(ctx)
        try:
            _goto(page, PLATFORMS[platform]["home_url"])
            return is_logged_in_url(platform, page.url)
        finally:
            ctx.close()


def _do_logout(platform: str, account: str, player) -> str:
    pdir = profile_dir(platform, account)
    if pdir.exists():
        shutil.rmtree(pdir, ignore_errors=True)
        _log(player, f"Removed {platform} session.")
        return f"✅ Signed out of {PLATFORMS[platform]['name']}; session deleted."
    return f"No saved {PLATFORMS[platform]['name']} session to remove, sir."


def ensure_session(platform: str, player=None, speak=None, force: bool = False) -> dict:
    """
    Compat helper used by other agents. Returns {success, message, method}.
    Checks the saved session; if absent/expired (or force), runs manual login.
    """
    platform = normalize_platform(platform)
    if not platform:
        return {"success": False, "message": "Unknown social platform."}
    name = PLATFORMS[platform]["name"]
    account = ""
    if not force:
        try:
            if _check_status(platform, account):
                return {"success": True, "message": f"Already logged in to {name}.",
                        "method": "existing_session"}
        except Exception:
            pass
    ok = _do_login(platform, account, player, speak)
    if ok:
        return {"success": True, "message": f"Connected to {name}, sir.", "method": "manual_login"}
    return {"success": False,
            "message": f"{name} login wasn't completed. Say 'social login {platform}' to try again."}


def _setup_text() -> str:
    return (
        "📱 Social login — the easy way (no stored passwords):\n"
        "  1. Say 'social login instagram' (or twitter, facebook, linkedin, tiktok).\n"
        "  2. A browser window opens — sign in with your normal username + password,\n"
        "     and complete any 2FA yourself. JARVIS never sees your password.\n"
        "  3. The session is saved locally (browser_profiles/social/, never pushed).\n"
        "Then use the social/instagram agents normally. 'social status' / 'social logout'."
    )


def social_browser_agent(parameters: dict, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "login")).lower().strip()
    platform = normalize_platform(params.get("platform", ""))
    account = (params.get("account") or params.get("username") or "").strip()

    if action in ("setup", "help", "instructions"):
        return _setup_text()
    if action == "list":
        connected = connected_platforms()
        if not connected:
            return "No social accounts connected yet. Say 'social login instagram' to start."
        return "Connected: " + ", ".join(PLATFORMS[p]["name"] for p in connected)
    if not platform:
        return ("Which platform, sir? instagram, twitter, facebook, linkedin, or tiktok. "
                "Example: 'social login instagram'.")

    name = PLATFORMS[platform]["name"]
    if action in ("login", "signin", "connect", "save"):
        ok = _do_login(platform, account, player, speak)
        return (f"✅ {name} connected. Session saved locally." if ok
                else f"{name} login wasn't completed in time. Say 'social login {platform}' to retry.")
    if action in ("status", "whoami"):
        try:
            ok = _check_status(platform, account)
        except Exception as e:
            return f"Status check failed: {e}"
        return f"✅ {name} session is active." if ok else f"{name} not connected — say 'social login {platform}'."
    if action in ("logout", "signout", "disconnect", "clear"):
        return _do_logout(platform, account, player)

    return f"❌ Unknown social action '{action}'. Try: login, status, logout, list, setup."
