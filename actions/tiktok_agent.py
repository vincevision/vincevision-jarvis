# actions/tiktok_agent.py
"""
JARVIS TikTok Agent
Supports: All browsers
Features: Login, Notifications, DMs, Send Messages,
          Post Videos, Like, Follow, Unfollow,
          Search, Comments, Profile Stats, Download,
          Recent Followers, Follower Count
Uses browser_control internally with credential_manager
"""

import time
import asyncio
import platform
from pathlib import Path

_OS = platform.system()

# ─────────────────────────────────────────────
# URLS
# ─────────────────────────────────────────────

_TIKTOK_URLS = {
    "home":          "https://www.tiktok.com",
    "login":         "https://www.tiktok.com/login",
    "notifications": "https://www.tiktok.com/notification",
    "messages":      "https://www.tiktok.com/messages",
    "upload":        "https://www.tiktok.com/upload",
    "explore":       "https://www.tiktok.com/explore",
    "following":     "https://www.tiktok.com/following",
}

# ─────────────────────────────────────────────
# LOGIN DETECTION
# ─────────────────────────────────────────────

_LOGIN_INDICATORS = [
    "for you",
    "following",
    "foryou",
    "upload",
    "messages",
    "inbox",
    "live",
]

_LOGOUT_INDICATORS = [
    "log in to tiktok",
    "sign up for tiktok",
    "/login",
    "phone / email / username",
    "continue with",
    "already have an account",
]

# ─────────────────────────────────────────────
# CREDENTIAL MANAGER
# ─────────────────────────────────────────────

def _get_tiktok_credentials() -> dict:
    """Get TikTok credentials from credential_manager."""
    try:
        from core.credential_manager import get_credential, has_credential
        if has_credential("tiktok", "username") and \
           has_credential("tiktok", "password"):
            return {
                "username": get_credential("tiktok", "username"),
                "password": get_credential("tiktok", "password"),
            }
    except Exception as e:
        print(f"[TikTok] Credential load error: {e}")
    return {}


def _save_tiktok_credentials(username: str, password: str) -> bool:
    """Save TikTok credentials securely."""
    try:
        from core.credential_manager import save_credential
        save_credential("tiktok", "username", username)
        save_credential("tiktok", "password", password)
        print(f"[TikTok] ✅ Credentials saved for {username}")
        return True
    except Exception as e:
        print(f"[TikTok] ❌ Could not save credentials: {e}")
        return False


def _prompt_for_credentials(speak=None, player=None) -> dict:
    """Prompt user for TikTok credentials."""
    msg = (
        "Sir, I need your TikTok credentials to continue. "
        "Please enter your TikTok username and password."
    )
    if speak:
        speak(msg)
    if player:
        player.write_log("[TikTok] Credentials required")

    print("\n" + "─" * 50)
    print("  JARVIS — TikTok Login Setup")
    print("─" * 50)

    try:
        import tkinter as tk
        from tkinter import simpledialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)

        username = simpledialog.askstring(
            "TikTok Login",
            "Enter your TikTok username or email:",
            parent=root
        )
        password = simpledialog.askstring(
            "TikTok Login",
            "Enter your TikTok password:",
            show="*",
            parent=root
        )
        root.destroy()

        if username and password:
            return {
                "username": username.strip(),
                "password": password.strip()
            }
    except Exception as e:
        print(f"[TikTok] GUI dialog failed: {e}")

    try:
        import getpass
        username = input("  TikTok Username/Email: ").strip()
        password = getpass.getpass("  TikTok Password:       ").strip()
        if username and password:
            return {"username": username, "password": password}
    except Exception as e:
        print(f"[TikTok] Terminal input error: {e}")

    return {}


def _ensure_credentials(speak=None, player=None) -> dict:
    """Get or prompt for credentials."""
    creds = _get_tiktok_credentials()
    if creds:
        print(f"[TikTok] ✅ Credentials found for {creds['username']}")
        return creds

    print("[TikTok] No credentials found. Prompting user...")
    if speak:
        speak(
            "Sir, I don't have your TikTok credentials saved. "
            "Please provide them now."
        )

    creds = _prompt_for_credentials(speak=speak, player=player)
    if not creds:
        return {}

    _save_tiktok_credentials(creds["username"], creds["password"])

    if speak:
        speak(
            f"TikTok credentials saved securely, sir. "
            f"Logging in as {creds['username']}."
        )
    return creds


# ─────────────────────────────────────────────
# CORE SESSION GETTER
# ─────────────────────────────────────────────

def _get_session(browser: str):
    """Get or create browser session safely."""
    from actions.browser_control import _registry

    sess = _registry.get(browser)

    if not sess._thread or not sess._thread.is_alive():
        print(f"[TikTok] Starting {browser} session...")
        sess.start()
        sess._ready.wait(timeout=15)
        time.sleep(2)
        print(f"[TikTok] ✅ {browser} session ready")

    if not sess._loop or not sess._loop.is_running():
        print(f"[TikTok] Loop not running, full restart...")
        with _registry._lock:
            _registry._sessions.pop(browser, None)
        sess = _registry.get(browser)
        sess._ready.wait(timeout=15)
        time.sleep(2)

    return sess


async def _pre_launch(sess) -> str:
    """Pre-launch browser context."""
    try:
        page = await sess._get_page()
        if page:
            return f"✅ Browser ready, page: {page.url}"
        return "⚠️ Page is None"
    except Exception as e:
        raise RuntimeError(f"Pre-launch failed: {e}") from e


def _run_tiktok(
    coro_fn,
    browser: str = "brave",
    timeout: int = 60,
    player=None
) -> str:
    """Safely run a TikTok coroutine with pre-launch."""
    from actions.browser_control import _registry

    MAX_RETRIES = 2

    for attempt in range(MAX_RETRIES):
        try:
            sess = _get_session(browser)
            print(f"[TikTok] Running (attempt {attempt + 1})...")

            try:
                launch_result = sess.run(
                    _pre_launch(sess), timeout=30
                )
                print(f"[TikTok] Pre-launch: {launch_result}")
            except Exception as pre_err:
                print(f"[TikTok] Pre-launch error: {pre_err}")
                if attempt < MAX_RETRIES - 1:
                    with _registry._lock:
                        old = _registry._sessions.pop(browser, None)
                        if old:
                            try: old.close()
                            except Exception: pass
                    time.sleep(4)
                    continue

            result = sess.run(coro_fn(sess), timeout=timeout)
            return result

        except Exception as e:
            error_str = str(e)
            print(f"[TikTok] ⚠️ Attempt {attempt + 1}: {error_str[:150]}")

            is_crash = any(x in error_str.lower() for x in [
                "closed", "target page", "browser has been",
                "connection refused", "not connected",
                "context or browser", "browsercontext",
                "crashed", "disconnected",
            ])

            if is_crash and attempt < MAX_RETRIES - 1:
                print("[TikTok] Context crashed — restarting...")
                try:
                    with _registry._lock:
                        old = _registry._sessions.pop(browser, None)
                        if old:
                            try: old.close()
                            except Exception: pass
                    time.sleep(4)
                except Exception as ce:
                    print(f"[TikTok] Cleanup error: {ce}")
                continue

            return (
                f"Sir, TikTok encountered an error. "
                f"Please try again. ({error_str[:100]})"
            )

    return "TikTok: Could not complete action. Please try again."


# ─────────────────────────────────────────────
# SAFE PAGE GETTER
# ─────────────────────────────────────────────

async def _safe_get_page(sess):
    """Safely get a page, retries 3 times."""
    for attempt in range(3):
        try:
            page = await sess._get_page()
            if page and not page.is_closed():
                return page
        except Exception as e:
            print(f"[TikTok] _get_page attempt {attempt + 1}: {e}")
            if attempt < 2:
                await asyncio.sleep(2)

    try:
        if sess._context:
            page = await sess._context.new_page()
            sess._page = page
            return page
    except Exception as e:
        print(f"[TikTok] new_page also failed: {e}")

    raise RuntimeError("Could not get browser page after 3 attempts.")


async def _safe_goto(page, url: str, timeout: int = 25000):
    """Navigate to URL, non-fatal on timeout."""
    try:
        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=timeout
        )
    except Exception as e:
        print(f"[TikTok] Goto non-fatal ({url[:40]}): {e}")
    await asyncio.sleep(3)


# ─────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────

async def _check_login_status(sess) -> dict:
    """Check if logged in to TikTok."""
    try:
        print("[TikTok] Checking login status...")
        page = await _safe_get_page(sess)
        await _safe_goto(page, _TIKTOK_URLS["home"])

        try:
            current_url = page.url.lower()
            page_text   = (await page.inner_text("body")).lower()
        except Exception as e:
            return {"logged_in": False, "message": f"Could not read page: {e}"}

        for sign in _LOGOUT_INDICATORS:
            if sign in page_text or sign in current_url:
                return {"logged_in": False, "message": "Not logged in to TikTok."}

        for sign in _LOGIN_INDICATORS:
            if sign in page_text or sign in current_url:
                return {"logged_in": True, "message": "Logged in to TikTok."}

        if "login" in current_url:
            return {"logged_in": False, "message": "Not logged in to TikTok."}

        if "tiktok.com" in current_url:
            return {"logged_in": True, "message": "TikTok session active."}

        return {"logged_in": False, "message": "Could not determine login status."}

    except Exception as e:
        return {"logged_in": False, "message": f"Login check failed: {e}"}


async def _do_login(sess, username: str, password: str) -> str:
    """Perform TikTok login with 2025 selectors."""
    try:
        page = await _safe_get_page(sess)
        print(f"[TikTok] Got page: {page.url}")

        print("[TikTok] Navigating to login page...")
        try:
            await page.goto(
                _TIKTOK_URLS["login"],
                wait_until="domcontentloaded",
                timeout=30000
            )
            print(f"[TikTok] ✅ At: {page.url}")
        except Exception as e:
            print(f"[TikTok] Login URL error: {e}")
            try:
                await page.goto(
                    _TIKTOK_URLS["home"],
                    wait_until="domcontentloaded",
                    timeout=30000
                )
            except Exception as e2:
                return f"Could not open TikTok: {e2}"

        await asyncio.sleep(5)

        try:
            body = await page.inner_text("body")
            print(f"[TikTok] Page preview: {body[:300]}")
        except Exception:
            pass

        # Step 1: Use phone/email/username
        clicked_method = False
        for selector in [
            'a:has-text("Use phone / email / username")',
            'a:has-text("Use phone")',
            'div:has-text("Use phone / email / username")',
            'span:has-text("Use phone / email / username")',
            '[data-e2e="channel-item"]',
            'div[class*="channel"]:has-text("phone")',
            'p:has-text("phone")',
        ]:
            try:
                els = await page.query_selector_all(selector)
                for el in els:
                    try:
                        txt = await el.inner_text()
                        if any(x in txt.lower() for x in ["phone", "email", "username"]):
                            await el.click()
                            await asyncio.sleep(2)
                            clicked_method = True
                            print(f"[TikTok] ✅ Clicked: '{txt.strip()[:50]}'")
                            break
                    except Exception:
                        continue
                if clicked_method:
                    break
            except Exception:
                continue

        if not clicked_method:
            print("[TikTok] ⚠️ No phone/email button found")
            try:
                await page.screenshot(
                    path=str(Path.home() / "Desktop" / "tiktok_debug.png")
                )
            except Exception:
                pass

        await asyncio.sleep(2)

        # Step 2: Email/username login
        for selector in [
            'a:has-text("Log in with email or username")',
            'a:has-text("Email or username")',
            'span:has-text("Log in with email")',
            'div:has-text("Log in with email")',
            'span:has-text("email or username")',
        ]:
            try:
                els = await page.query_selector_all(selector)
                for el in els:
                    try:
                        txt = await el.inner_text()
                        if any(x in txt.lower() for x in ["email", "username"]):
                            await el.click()
                            await asyncio.sleep(2)
                            print(f"[TikTok] ✅ Email login: '{txt.strip()[:50]}'")
                            break
                    except Exception:
                        continue
            except Exception:
                continue

        await asyncio.sleep(2)

        # Step 3: Type username
        username_typed = False
        for selector in [
            'input[name="username"]',
            'input[autocomplete="username"]',
            'input[placeholder*="email"]',
            'input[placeholder*="username"]',
            'input[placeholder*="Phone"]',
            '[data-e2e="input-username"]',
            'input[type="text"]',
        ]:
            try:
                el = await page.query_selector(selector)
                if el and await el.is_visible():
                    await el.click()
                    await asyncio.sleep(0.3)
                    await el.fill("")
                    await el.fill(username)
                    await asyncio.sleep(0.5)
                    val = await el.input_value()
                    if val:
                        username_typed = True
                        print(f"[TikTok] ✅ Username typed via '{selector}'")
                        break
            except Exception:
                continue

        if not username_typed:
            try:
                await page.screenshot(
                    path=str(Path.home() / "Desktop" / "tiktok_login_debug.png")
                )
            except Exception:
                pass
            return (
                "Sir, TikTok login form not found. "
                "Please log in manually, then say 'open TikTok'."
            )

        # Step 4: Type password
        password_typed = False
        for selector in [
            'input[type="password"]',
            'input[name="password"]',
            '[data-e2e="input-password"]',
            'input[autocomplete="current-password"]',
        ]:
            try:
                el = await page.query_selector(selector)
                if el and await el.is_visible():
                    await el.click()
                    await asyncio.sleep(0.3)
                    await el.fill("")
                    await el.fill(password)
                    await asyncio.sleep(0.5)
                    password_typed = True
                    print("[TikTok] ✅ Password typed")
                    break
            except Exception:
                continue

        if not password_typed:
            return "Sir, password field not found. Please log in manually."

        await asyncio.sleep(1)

        # Step 5: Click Login
        login_clicked = False
        for selector in [
            'button[type="submit"]',
            '[data-e2e="login-button"]',
            'button:has-text("Log in")',
            'button:has-text("Login")',
        ]:
            try:
                el = await page.query_selector(selector)
                if el and await el.is_visible():
                    await el.click()
                    login_clicked = True
                    print(f"[TikTok] ✅ Login clicked: {selector}")
                    await asyncio.sleep(8)
                    break
            except Exception:
                continue

        if not login_clicked:
            await page.keyboard.press("Enter")
            await asyncio.sleep(8)

        # Step 6: Verify
        try:
            final_url = page.url.lower()
            page_text = (await page.inner_text("body")).lower()
        except Exception:
            return "Login attempted. Please check the browser."

        if any(x in page_text for x in ["captcha", "verify", "puzzle", "slide", "robot"]):
            return "Sir, TikTok is showing a CAPTCHA. Please solve it manually."

        if any(x in page_text for x in ["for you", "following", "foryou", "upload", "messages"]):
            return f"✅ Successfully logged in to TikTok as {username}."

        if any(x in page_text for x in ["incorrect", "wrong", "invalid"]):
            return "Sir, login failed — username or password may be incorrect."

        return "Login attempted. If verification needed, complete it manually."

    except Exception as e:
        print(f"[TikTok] _do_login exception: {e}")
        import traceback
        traceback.print_exc()
        return f"Login error: {e}"


async def _ensure_logged_in(sess, speak=None, player=None, force_login=False) -> tuple:
    """Check login and auto-login if needed."""
    if not force_login:
        status = await _check_login_status(sess)
        if status["logged_in"]:
            print("[TikTok] ✅ Already logged in")
            return True, status["message"]

    print("[TikTok] Not logged in — attempting auto-login...")
    creds = _ensure_credentials(speak=speak, player=player)
    if not creds:
        return False, "Sir, I need your TikTok credentials. Say 'setup TikTok'."

    result = await _do_login(sess, creds["username"], creds["password"])
    await asyncio.sleep(2)
    status = await _check_login_status(sess)
    return status["logged_in"], result


# ─────────────────────────────────────────────
# HELPER: EXTRACT PROFILE STATS
# ─────────────────────────────────────────────

async def _extract_profile_stats(page) -> dict:
    """
    Extract profile stats using EXACT TikTok data-e2e selectors.
    Returns dict with all profile data.
    """
    stats = {
        "username":      "",
        "display_name":  "",
        "followers":     "",
        "following":     "",
        "likes":         "",
        "bio":           "",
        "videos":        0,
    }

    # Username
    try:
        el = await page.query_selector('[data-e2e="user-subtitle"]')
        if el:
            stats["username"] = await el.inner_text()
    except Exception:
        pass

    # Display name
    try:
        el = await page.query_selector('[data-e2e="user-title"]')
        if el:
            stats["display_name"] = await el.inner_text()
    except Exception:
        pass

    # Followers count
    try:
        el = await page.query_selector('[data-e2e="followers-count"]')
        if el:
            stats["followers"] = await el.inner_text()
    except Exception:
        pass

    # Following count
    try:
        el = await page.query_selector('[data-e2e="following-count"]')
        if el:
            stats["following"] = await el.inner_text()
    except Exception:
        pass

    # Likes count
    try:
        el = await page.query_selector('[data-e2e="likes-count"]')
        if el:
            stats["likes"] = await el.inner_text()
    except Exception:
        pass

    # Bio
    try:
        el = await page.query_selector('[data-e2e="user-bio"]')
        if el:
            stats["bio"] = await el.inner_text()
    except Exception:
        pass

    # Video count
    try:
        els = await page.query_selector_all('[data-e2e="user-post-item"]')
        stats["videos"] = len(els)
    except Exception:
        pass

    return stats


# ─────────────────────────────────────────────
# HELPER: EXTRACT NOTIFICATION DETAILS
# ─────────────────────────────────────────────

async def _extract_notifications(page) -> dict:
    """
    Extract detailed notification info.
    Returns dict with categorized notifications.
    """
    result = {
        "all":        [],
        "follows":    [],
        "likes":      [],
        "comments":   [],
        "mentions":   [],
        "count":      0,
    }

    try:
        # Get all notification items
        items = await page.query_selector_all(
            '[data-e2e="notification-item"], '
            'div[class*="NotificationItem"], '
            'div[class*="notification"]'
        )

        for item in items[:30]:
            try:
                txt = (await item.inner_text()).strip()
                if not txt or len(txt) < 5:
                    continue

                entry = txt.replace("\n", " ").strip()
                result["all"].append(entry)

                lower = entry.lower()
                if "followed you" in lower or "started following" in lower:
                    result["follows"].append(entry)
                elif "liked your" in lower:
                    result["likes"].append(entry)
                elif "commented" in lower or "replied" in lower:
                    result["comments"].append(entry)
                elif "mentioned you" in lower:
                    result["mentions"].append(entry)

            except Exception:
                continue

        # If no structured items found, fallback to page text
        if not result["all"]:
            text = await page.inner_text("body")
            lines = [
                l.strip() for l in text.split("\n")
                if l.strip() and len(l.strip()) > 10
            ]
            filtered = [
                l for l in lines
                if not any(x in l.lower() for x in [
                    "cookie", "privacy", "download app",
                    "©", "tiktok for good", "terms",
                    "explore", "for you", "following",
                    "messages", "upload", "live"
                ])
            ][:25]

            for entry in filtered:
                result["all"].append(entry)
                lower = entry.lower()
                if "followed" in lower or "following" in lower:
                    result["follows"].append(entry)
                elif "liked" in lower:
                    result["likes"].append(entry)
                elif "comment" in lower or "replied" in lower:
                    result["comments"].append(entry)
                elif "mention" in lower:
                    result["mentions"].append(entry)

        result["count"] = len(result["all"])

    except Exception as e:
        print(f"[TikTok] Notification extract error: {e}")

    return result


# ─────────────────────────────────────────────
# HELPER: GET FOLLOWERS LIST
# ─────────────────────────────────────────────

async def _get_followers_list(page, username: str, max_count: int = 20) -> list:
    """
    Open followers dialog and extract list of followers.
    Returns list of usernames.
    """
    followers = []

    try:
        # Click on "Followers" text/number
        for selector in [
            '[data-e2e="followers"]',
            '[data-e2e="followers-count"]',
            'span:has-text("Followers")',
        ]:
            try:
                el = await page.query_selector(selector)
                if el:
                    await el.click()
                    await asyncio.sleep(3)
                    print("[TikTok] ✅ Opened followers list")
                    break
            except Exception:
                continue

        # Extract followers from the modal/dialog
        # Scroll to load more
        for scroll_i in range(3):
            try:
                # Get all user items in the followers list
                items = await page.query_selector_all(
                    '[data-e2e="user-item"], '
                    'div[class*="UserItem"], '
                    'div[class*="follower-item"], '
                    'a[data-e2e="user-card"], '
                    'div[class*="UserList"] a'
                )

                for item in items:
                    try:
                        txt = (await item.inner_text()).strip()
                        if txt and len(txt) > 1 and txt not in followers:
                            # Extract just username
                            username_line = txt.split("\n")[0].strip()
                            if username_line and username_line not in followers:
                                followers.append(username_line)
                    except Exception:
                        continue

                if len(followers) >= max_count:
                    break

                # Scroll down in dialog
                dialog = await page.query_selector(
                    'div[class*="UserList"], '
                    'div[role="dialog"], '
                    'div[class*="Modal"]'
                )
                if dialog:
                    await dialog.evaluate(
                        'el => el.scrollTop = el.scrollHeight'
                    )
                    await asyncio.sleep(2)

            except Exception:
                break

        # Close dialog
        try:
            close_btn = await page.query_selector(
                'button[aria-label="Close"], '
                'div[class*="close"], '
                'svg[aria-label="Close"]'
            )
            if close_btn:
                await close_btn.click()
        except Exception:
            await page.keyboard.press("Escape")

    except Exception as e:
        print(f"[TikTok] Followers list error: {e}")

    return followers[:max_count]


# ─────────────────────────────────────────────
# TIKTOK COROUTINES
# ─────────────────────────────────────────────

async def _tt_open(sess, speak=None, player=None) -> str:
    """Open TikTok homepage."""
    logged_in, msg = await _ensure_logged_in(sess, speak=speak, player=player)
    if not logged_in:
        return msg

    page = await _safe_get_page(sess)
    await _safe_goto(page, _TIKTOK_URLS["home"])
    return "TikTok opened, sir."


async def _tt_notifications(sess, speak=None, player=None) -> str:
    """Read TikTok notifications with detailed breakdown."""
    logged_in, msg = await _ensure_logged_in(sess, speak=speak, player=player)
    if not logged_in:
        return msg

    page = await _safe_get_page(sess)
    await _safe_goto(page, _TIKTOK_URLS["notifications"])
    await asyncio.sleep(2)

    notifs = await _extract_notifications(page)

    if notifs["count"] == 0:
        return "No notifications found, sir."

    # Build detailed response
    parts = [f"You have {notifs['count']} notifications, sir."]

    if notifs["follows"]:
        parts.append(
            f"\n📱 New followers ({len(notifs['follows'])}):"
        )
        for f in notifs["follows"][:10]:
            parts.append(f"  • {f}")

    if notifs["likes"]:
        parts.append(
            f"\n❤️ Likes ({len(notifs['likes'])}):"
        )
        for l in notifs["likes"][:10]:
            parts.append(f"  • {l}")

    if notifs["comments"]:
        parts.append(
            f"\n💬 Comments ({len(notifs['comments'])}):"
        )
        for c in notifs["comments"][:10]:
            parts.append(f"  • {c}")

    if notifs["mentions"]:
        parts.append(
            f"\n🔔 Mentions ({len(notifs['mentions'])}):"
        )
        for m in notifs["mentions"][:10]:
            parts.append(f"  • {m}")

    # If nothing was categorized, show raw
    if not any([notifs["follows"], notifs["likes"],
                notifs["comments"], notifs["mentions"]]):
        parts.append("\nRecent activity:")
        for a in notifs["all"][:15]:
            parts.append(f"  • {a}")

    return "\n".join(parts)


async def _tt_messages(sess, speak=None, player=None) -> str:
    """Read TikTok DMs/messages inbox."""
    logged_in, msg = await _ensure_logged_in(sess, speak=speak, player=player)
    if not logged_in:
        return msg

    page = await _safe_get_page(sess)
    await _safe_goto(page, _TIKTOK_URLS["messages"])
    await asyncio.sleep(2)

    try:
        # Try to get conversation list
        conversations = []
        items = await page.query_selector_all(
            '[data-e2e="message-item"], '
            'div[class*="ConversationItem"], '
            'div[class*="chat-item"]'
        )

        for item in items[:20]:
            try:
                txt = (await item.inner_text()).strip()
                if txt and len(txt) > 3:
                    # Format: "username\nlast message\ntime"
                    clean = txt.replace("\n", " — ")
                    conversations.append(clean)
            except Exception:
                continue

        if conversations:
            parts = [f"You have {len(conversations)} conversations, sir:"]
            for i, conv in enumerate(conversations[:15], 1):
                parts.append(f"  {i}. {conv[:80]}")
            return "\n".join(parts)

        # Fallback: raw page text
        text = await page.inner_text("body")
        lines = [
            l.strip() for l in text.split("\n")
            if l.strip() and len(l.strip()) > 3
        ]
        filtered = [
            l for l in lines
            if not any(x in l.lower() for x in [
                "cookie", "privacy", "download",
                "terms", "©", "tiktok for good"
            ])
        ][:25]

        if filtered:
            return "TikTok messages:\n" + "\n".join(filtered)
        return "No messages found, sir."

    except Exception as e:
        return f"Could not read messages: {e}"


async def _tt_send_message(
    sess, username: str, message: str,
    speak=None, player=None
) -> str:
    """Send a DM to a TikTok user."""
    logged_in, msg = await _ensure_logged_in(sess, speak=speak, player=player)
    if not logged_in:
        return msg

    page = await _safe_get_page(sess)
    await _safe_goto(page, _TIKTOK_URLS["messages"])

    try:
        # Method 1: Search for existing conversation
        existing_found = False

        # Look for search box in messages
        for selector in [
            'input[placeholder*="Search"]',
            'input[data-e2e="search-input"]',
            'input[type="search"]',
        ]:
            try:
                el = await page.query_selector(selector)
                if el and await el.is_visible():
                    await el.fill(username)
                    await asyncio.sleep(2)

                    # Click on matching user
                    for user_sel in [
                        f'span:has-text("{username}")',
                        f'div:has-text("@{username}")',
                        f'[data-e2e="user-item"]',
                    ]:
                        try:
                            user_el = await page.query_selector(user_sel)
                            if user_el:
                                await user_el.click()
                                await asyncio.sleep(2)
                                existing_found = True
                                break
                        except Exception:
                            continue
                    break
            except Exception:
                continue

        # Method 2: Go to user profile and click Message
        if not existing_found:
            profile_url = f"https://www.tiktok.com/@{username}"
            await _safe_goto(page, profile_url)

            for selector in [
                'button:has-text("Message")',
                '[data-e2e="message-button"]',
                'a:has-text("Message")',
                'button[aria-label="Message"]',
            ]:
                try:
                    el = await page.query_selector(selector)
                    if el and await el.is_visible():
                        await el.click()
                        await asyncio.sleep(3)
                        existing_found = True
                        print(f"[TikTok] ✅ Opened DM via profile: {selector}")
                        break
                except Exception:
                    continue

        if not existing_found:
            # Method 3: Try compose new message
            await _safe_goto(page, _TIKTOK_URLS["messages"])

            for selector in [
                '[data-e2e="new-message-button"]',
                'button[aria-label="New Message"]',
                'button:has-text("New Message")',
                'svg[data-e2e="compose-icon"]',
            ]:
                try:
                    el = await page.query_selector(selector)
                    if el:
                        await el.click()
                        await asyncio.sleep(2)

                        # Search for user in compose
                        for inp_sel in [
                            'input[placeholder*="Search"]',
                            'input[type="text"]',
                        ]:
                            try:
                                inp = await page.query_selector(inp_sel)
                                if inp:
                                    await inp.fill(username)
                                    await asyncio.sleep(2)

                                    # Click user
                                    for u_sel in [
                                        f'span:has-text("{username}")',
                                        f'div:has-text("{username}")',
                                    ]:
                                        try:
                                            u = await page.query_selector(u_sel)
                                            if u:
                                                await u.click()
                                                await asyncio.sleep(1)
                                                break
                                        except Exception:
                                            continue

                                    # Click Next/Chat button
                                    for btn_sel in [
                                        'button:has-text("Next")',
                                        'button:has-text("Chat")',
                                    ]:
                                        try:
                                            btn = await page.query_selector(btn_sel)
                                            if btn:
                                                await btn.click()
                                                await asyncio.sleep(2)
                                                existing_found = True
                                                break
                                        except Exception:
                                            continue
                                    break
                            except Exception:
                                continue
                        break
                except Exception:
                    continue

        # Now type the message
        message_sent = False
        for selector in [
            '[data-e2e="message-input"]',
            'div[contenteditable="true"]',
            'div[class*="DraftEditor"]',
            'textarea[placeholder*="Send"]',
            'textarea[placeholder*="message"]',
            'div[role="textbox"]',
            'p[data-placeholder]',
        ]:
            try:
                el = await page.query_selector(selector)
                if el:
                    await el.click()
                    await asyncio.sleep(0.5)

                    # Try fill first
                    try:
                        await el.fill(message)
                    except Exception:
                        # Fallback: type character by character
                        await page.type(selector, message, delay=50)

                    await asyncio.sleep(1)

                    # Send: try button first, then Enter
                    for send_sel in [
                        '[data-e2e="send-message-button"]',
                        'button[aria-label="Send"]',
                        'button:has-text("Send")',
                    ]:
                        try:
                            send_btn = await page.query_selector(send_sel)
                            if send_btn:
                                await send_btn.click()
                                message_sent = True
                                break
                        except Exception:
                            continue

                    if not message_sent:
                        await page.keyboard.press("Enter")
                        message_sent = True

                    break
            except Exception:
                continue

        if message_sent:
            return f"✅ Message sent to @{username}: {message[:80]}"

        # Take debug screenshot
        try:
            await page.screenshot(
                path=str(Path.home() / "Desktop" / "tiktok_msg_debug.png")
            )
            print("[TikTok] 📸 Message debug screenshot saved")
        except Exception:
            pass

        return (
            f"Could not auto-send to @{username}. "
            f"TikTok is open — please type and send: {message}"
        )

    except Exception as e:
        return f"Send message failed: {e}"


async def _tt_post_video(
    sess, video_path: str, caption: str,
    speak=None, player=None
) -> str:
    """Post a video to TikTok."""
    logged_in, msg = await _ensure_logged_in(sess, speak=speak, player=player)
    if not logged_in:
        return msg

    if not video_path:
        return "Sir, please provide a video file path to post."

    vp = Path(video_path)
    if not vp.exists():
        return f"Sir, video file not found: {video_path}"

    page = await _safe_get_page(sess)
    await _safe_goto(page, _TIKTOK_URLS["upload"])
    await asyncio.sleep(2)

    try:
        for selector in ['input[type="file"]', '[data-e2e="upload-input"]']:
            try:
                el = await page.query_selector(selector)
                if el:
                    await el.set_input_files(str(vp))
                    await asyncio.sleep(5)
                    break
            except Exception:
                continue

        if caption:
            for selector in [
                '[data-e2e="caption-input"]',
                'div[contenteditable="true"]',
                '.DraftEditor-editorContainer',
            ]:
                try:
                    el = await page.query_selector(selector)
                    if el:
                        await el.click()
                        await page.keyboard.press("Control+a")
                        await page.type(selector, caption, delay=50)
                        break
                except Exception:
                    continue

        return (
            f"✅ Video uploaded: {vp.name}. "
            f"Caption: {caption[:60]}. "
            "Review and click Post to publish."
        )
    except Exception as e:
        return f"Video post failed: {e}"


async def _tt_like(sess, url: str, speak=None, player=None) -> str:
    """Like a TikTok video."""
    logged_in, msg = await _ensure_logged_in(sess, speak=speak, player=player)
    if not logged_in:
        return msg

    page = await _safe_get_page(sess)
    await _safe_goto(page, url)

    try:
        for selector in [
            '[data-e2e="like-icon"]',
            'span[data-e2e="like-icon"]',
            'button[aria-label="Like"]',
        ]:
            try:
                el = await page.query_selector(selector)
                if el:
                    await el.click()
                    await asyncio.sleep(1)
                    return "✅ Liked TikTok video."
            except Exception:
                continue
        return "Could not find like button. Please like manually."
    except Exception as e:
        return f"Like failed: {e}"


async def _tt_comment(
    sess, url: str, comment: str,
    speak=None, player=None
) -> str:
    """Comment on a TikTok video."""
    logged_in, msg = await _ensure_logged_in(sess, speak=speak, player=player)
    if not logged_in:
        return msg

    page = await _safe_get_page(sess)
    await _safe_goto(page, url)

    try:
        for selector in [
            '[data-e2e="comment-icon"]',
            '[aria-label="Comments"]',
        ]:
            try:
                el = await page.query_selector(selector)
                if el:
                    await el.click()
                    await asyncio.sleep(2)
                    break
            except Exception:
                continue

        for selector in [
            '[data-e2e="comment-input"]',
            'input[placeholder*="comment"]',
            'div[contenteditable="true"]',
        ]:
            try:
                el = await page.query_selector(selector)
                if el:
                    await el.click()
                    await page.type(selector, comment, delay=50)
                    await asyncio.sleep(1)

                    for btn in ['[data-e2e="comment-post"]', 'button:has-text("Post")']:
                        try:
                            b = await page.query_selector(btn)
                            if b:
                                await b.click()
                                return f"✅ Comment posted: {comment[:80]}"
                        except Exception:
                            continue

                    await page.keyboard.press("Enter")
                    return f"✅ Comment posted: {comment[:80]}"
            except Exception:
                continue

        return f"Could not post comment. Text: {comment}"
    except Exception as e:
        return f"Comment failed: {e}"


async def _tt_follow(sess, username: str, speak=None, player=None) -> str:
    """Follow a TikTok user."""
    logged_in, msg = await _ensure_logged_in(sess, speak=speak, player=player)
    if not logged_in:
        return msg

    page = await _safe_get_page(sess)
    await _safe_goto(page, f"https://www.tiktok.com/@{username}")

    try:
        # First get their stats
        stats = await _extract_profile_stats(page)

        for selector in [
            '[data-e2e="follow-button"]',
            'button:has-text("Follow")',
        ]:
            try:
                el = await page.query_selector(selector)
                if el:
                    btn_text = await el.inner_text()
                    if "following" in btn_text.lower():
                        return (
                            f"You're already following @{username}, sir. "
                            f"They have {stats.get('followers', '?')} followers "
                            f"and {stats.get('likes', '?')} likes."
                        )

                    await el.click()
                    await asyncio.sleep(1)
                    return (
                        f"✅ Now following @{username} on TikTok. "
                        f"They have {stats.get('followers', '?')} followers "
                        f"and {stats.get('likes', '?')} likes."
                    )
            except Exception:
                continue

        return f"Opened @{username}'s profile. Click Follow manually."
    except Exception as e:
        return f"Follow failed: {e}"


async def _tt_unfollow(sess, username: str, speak=None, player=None) -> str:
    """Unfollow a TikTok user."""
    logged_in, msg = await _ensure_logged_in(sess, speak=speak, player=player)
    if not logged_in:
        return msg

    page = await _safe_get_page(sess)
    await _safe_goto(page, f"https://www.tiktok.com/@{username}")

    try:
        stats = await _extract_profile_stats(page)

        for selector in [
            'button:has-text("Following")',
            '[data-e2e="follow-button"]:has-text("Following")',
        ]:
            try:
                el = await page.query_selector(selector)
                if el:
                    await el.click()
                    await asyncio.sleep(1)

                    for confirm in [
                        'button:has-text("Unfollow")',
                        '[data-e2e="unfollow-popup-unfollow-btn"]',
                    ]:
                        try:
                            c = await page.query_selector(confirm)
                            if c:
                                await c.click()
                                await asyncio.sleep(1)
                                break
                        except Exception:
                            continue

                    return (
                        f"✅ Unfollowed @{username}. "
                        f"They had {stats.get('followers', '?')} followers."
                    )
            except Exception:
                continue

        return f"Opened @{username}'s profile. Click Unfollow manually."
    except Exception as e:
        return f"Unfollow failed: {e}"


async def _tt_search(
    sess, query: str, search_type: str = "videos",
    speak=None, player=None
) -> str:
    """Search TikTok."""
    logged_in, msg = await _ensure_logged_in(sess, speak=speak, player=player)
    if not logged_in:
        return msg

    search_url = f"https://www.tiktok.com/search?q={query.replace(' ', '%20')}"
    page = await _safe_get_page(sess)
    await _safe_goto(page, search_url)
    await asyncio.sleep(2)

    if search_type in ("users", "accounts"):
        for sel in ['a:has-text("Users")', '[data-e2e="search-tab-users"]']:
            try:
                el = await page.query_selector(sel)
                if el:
                    await el.click()
                    await asyncio.sleep(2)
                    break
            except Exception:
                continue

    try:
        text = await page.inner_text("body")
        lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 5]
        filtered = [
            l for l in lines
            if not any(x in l.lower() for x in [
                "cookie", "privacy", "download", "terms", "©"
            ])
        ][:25]

        if filtered:
            return f"TikTok search '{query}':\n" + "\n".join(filtered)
        return f"No results for '{query}'."
    except Exception as e:
        return f"Search failed: {e}"


async def _tt_profile(
    sess, username: str = "",
    speak=None, player=None
) -> str:
    """View detailed TikTok profile stats."""
    logged_in, msg = await _ensure_logged_in(sess, speak=speak, player=player)
    if not logged_in:
        return msg

    page = await _safe_get_page(sess)

    if not username:
        creds = _get_tiktok_credentials()
        username = creds.get("username", "")
        if not username:
            return "Sir, please provide a username to view profile."

    url = f"https://www.tiktok.com/@{username}"
    await _safe_goto(page, url)
    await asyncio.sleep(2)

    stats = await _extract_profile_stats(page)

    if not stats["followers"] and not stats["following"]:
        return f"Could not extract stats for @{username}."

    target = f"@{username}"
    parts = [f"TikTok profile for {target}:"]
    parts.append(f"  👤 Display name: {stats['display_name'] or 'N/A'}")
    parts.append(f"  📊 Followers: {stats['followers']}")
    parts.append(f"  📊 Following: {stats['following']}")
    parts.append(f"  ❤️ Total likes: {stats['likes']}")
    parts.append(f"  🎬 Videos visible: {stats['videos']}")
    if stats["bio"] and stats["bio"] != "No bio yet.":
        parts.append(f"  📝 Bio: {stats['bio']}")

    return "\n".join(parts)


async def _tt_followers(
    sess, username: str = "",
    speak=None, player=None
) -> str:
    """View recent followers list."""
    logged_in, msg = await _ensure_logged_in(sess, speak=speak, player=player)
    if not logged_in:
        return msg

    page = await _safe_get_page(sess)

    if not username:
        creds = _get_tiktok_credentials()
        username = creds.get("username", "")

    if not username:
        return "Sir, please provide a username."

    url = f"https://www.tiktok.com/@{username}"
    await _safe_goto(page, url)
    await asyncio.sleep(2)

    # Get stats first
    stats = await _extract_profile_stats(page)

    # Get followers list
    followers = await _get_followers_list(page, username, max_count=20)

    parts = [
        f"@{username} has {stats.get('followers', '?')} followers, sir."
    ]

    if followers:
        parts.append(f"\nRecent followers ({len(followers)}):")
        for i, f in enumerate(followers, 1):
            parts.append(f"  {i}. {f}")
    else:
        parts.append("Could not extract individual follower names.")

    return "\n".join(parts)


async def _tt_download(
    sess, url: str, save_path: str = "",
    speak=None, player=None
) -> str:
    """Download a TikTok video."""
    logged_in, msg = await _ensure_logged_in(sess, speak=speak, player=player)
    if not logged_in:
        return msg

    if not url:
        return "Sir, please provide a TikTok video URL."

    if not save_path:
        downloads = Path.home() / "Downloads"
        downloads.mkdir(exist_ok=True)
        save_path = str(downloads)

    try:
        import subprocess, shutil as sh
        if sh.which("yt-dlp"):
            out = str(Path(save_path) / "%(title)s.%(ext)s")
            r = subprocess.run(
                ["yt-dlp", "-o", out, url],
                capture_output=True, text=True, timeout=120
            )
            if r.returncode == 0:
                return f"✅ Video downloaded to {save_path}."
    except Exception:
        pass

    try:
        page = await _safe_get_page(sess)
        await _safe_goto(page, "https://snaptik.app")
        for sel in ['input[placeholder*="TikTok"]', 'input[name="url"]', 'input[type="text"]']:
            try:
                el = await page.query_selector(sel)
                if el:
                    await el.fill(url)
                    break
            except Exception:
                continue
        for sel in ['button[type="submit"]', 'button:has-text("Download")']:
            try:
                el = await page.query_selector(sel)
                if el:
                    await el.click()
                    await asyncio.sleep(4)
                    break
            except Exception:
                continue
        return "SnapTik opened. Click Download on the page."
    except Exception as e:
        return f"Download failed. Install yt-dlp: pip install yt-dlp. Error: {e}"


async def _tt_logout(sess, speak=None, player=None) -> str:
    """Log out of TikTok."""
    try:
        page = await _safe_get_page(sess)
        await _safe_goto(page, _TIKTOK_URLS["home"])

        for sel in ['[data-e2e="nav-profile"]', '[aria-label="Profile"]']:
            try:
                el = await page.query_selector(sel)
                if el:
                    await el.click()
                    await asyncio.sleep(2)
                    break
            except Exception:
                continue

        for sel in ['span:has-text("Log out")', 'div:has-text("Log out")', '[data-e2e="logout-button"]']:
            try:
                el = await page.query_selector(sel)
                if el:
                    await el.click()
                    await asyncio.sleep(2)
                    return "✅ Logged out of TikTok."
            except Exception:
                continue

        return "Could not find log out button. Log out manually."
    except Exception as e:
        return f"Logout failed: {e}"


async def _tt_setup(sess, speak=None, player=None) -> str:
    """Force credential setup."""
    try:
        print("[TikTok] 🔄 Running setup wizard...")
        if speak:
            speak("Starting TikTok setup, sir.")

        creds = _prompt_for_credentials(speak=speak, player=player)
        if not creds:
            return "Setup cancelled."

        _save_tiktok_credentials(creds["username"], creds["password"])
        await asyncio.sleep(2)

        try:
            page = await _safe_get_page(sess)
        except Exception as e:
            return f"Credentials saved for {creds['username']}. Say 'open TikTok' to login."

        result = await _do_login(sess, creds["username"], creds["password"])
        return f"TikTok setup complete. {result}"
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"Setup failed: {e}"


# ─────────────────────────────────────────────
# ROUTING TABLES
# ─────────────────────────────────────────────

_ROUTES = {
    "open":           "_tt_open",
    "home":           "_tt_open",
    "notifications":  "_tt_notifications",
    "notify":         "_tt_notifications",
    "inbox":          "_tt_notifications",
    "messages":       "_tt_messages",
    "dms":            "_tt_messages",
    "profile":        "_tt_profile",
    "stats":          "_tt_profile",
    "followers":      "_tt_followers",
    "follower_list":  "_tt_followers",
    "recent_followers":"_tt_followers",
    "search":         "_tt_search",
    "logout":         "_tt_logout",
    "setup":          "_tt_setup",
    "login":          "_tt_setup",
}

_PARAM_ROUTES = {
    "send_message": "_tt_send_message",
    "send":         "_tt_send_message",
    "message":      "_tt_send_message",
    "post":         "_tt_post_video",
    "upload":       "_tt_post_video",
    "like":         "_tt_like",
    "comment":      "_tt_comment",
    "follow":       "_tt_follow",
    "unfollow":     "_tt_unfollow",
    "download":     "_tt_download",
}


# ─────────────────────────────────────────────
# MAIN AGENT
# ─────────────────────────────────────────────

def tiktok_agent(
    parameters: dict,
    player=None,
    speak=None,
) -> str:
    """Main TikTok agent entry point."""
    params      = parameters or {}
    action      = params.get("action", "open").lower().strip()
    browser     = params.get("browser", "brave").lower().strip()
    username    = params.get("username", "").strip()
    message     = params.get("message", "").strip()
    url         = params.get("url", "").strip()
    query       = params.get("query", "").strip()
    caption     = params.get("caption", "").strip()
    content     = params.get("content", caption).strip()
    video       = params.get("video_path", params.get("video", "")).strip()
    save_path   = params.get("save_path", "").strip()
    search_type = params.get("search_type", "videos").strip()

    if player:
        player.write_log(f"[TikTok] → {action}")
    print(f"[TikTok] Action: {action} | Browser: {browser}")

    try:
        # Simple routes
        if action in _ROUTES:
            route_name = _ROUTES[action]

            route_map = {
                "_tt_open":          lambda s: _tt_open(s, speak, player),
                "_tt_notifications": lambda s: _tt_notifications(s, speak, player),
                "_tt_messages":      lambda s: _tt_messages(s, speak, player),
                "_tt_profile":       lambda s: _tt_profile(s, username, speak, player),
                "_tt_followers":     lambda s: _tt_followers(s, username, speak, player),
                "_tt_search":        lambda s: _tt_search(s, query, search_type, speak, player),
                "_tt_logout":        lambda s: _tt_logout(s, speak, player),
                "_tt_setup":         lambda s: _tt_setup(s, speak, player),
            }

            coro_fn = route_map.get(route_name)
            if not coro_fn:
                return f"Internal routing error for: {action}"

            result = _run_tiktok(coro_fn, browser, timeout=60, player=player)

        # Parameter routes
        elif action in _PARAM_ROUTES:

            if action in ("send_message", "send", "message"):
                if not username:
                    return "Sir, please provide a username to message."
                if not message:
                    return "Sir, please provide a message to send."
                coro_fn = lambda s: _tt_send_message(s, username, message, speak, player)

            elif action in ("post", "upload"):
                coro_fn = lambda s: _tt_post_video(s, video, content, speak, player)

            elif action == "like":
                if not url:
                    return "Sir, please provide a TikTok URL to like."
                coro_fn = lambda s: _tt_like(s, url, speak, player)

            elif action == "comment":
                if not url:
                    return "Sir, please provide a TikTok URL to comment on."
                if not content:
                    return "Sir, please provide comment text."
                coro_fn = lambda s: _tt_comment(s, url, content, speak, player)

            elif action == "follow":
                if not username:
                    return "Sir, please provide a username to follow."
                coro_fn = lambda s: _tt_follow(s, username, speak, player)

            elif action == "unfollow":
                if not username:
                    return "Sir, please provide a username to unfollow."
                coro_fn = lambda s: _tt_unfollow(s, username, speak, player)

            elif action == "download":
                if not url:
                    return "Sir, please provide a TikTok URL to download."
                coro_fn = lambda s: _tt_download(s, url, save_path, speak, player)

            else:
                return f"Unknown action: {action}"

            result = _run_tiktok(coro_fn, browser, timeout=90, player=player)

        else:
            available = list(_ROUTES.keys()) + list(_PARAM_ROUTES.keys())
            return f"Unknown action: '{action}'. Available: {', '.join(available)}"

        if speak and result and len(result) < 300:
            speak(result)

        return result

    except Exception as e:
        err = f"TikTok agent error: {e}"
        print(f"[TikTok] ❌ {err}")
        import traceback
        traceback.print_exc()
        if speak:
            speak(f"Sir, TikTok error: {str(e)[:100]}")
        return err