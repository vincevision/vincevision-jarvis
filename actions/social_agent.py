# social_agent.py
"""
JARVIS Social Media Agent
Supports: Instagram, Twitter/X, LinkedIn, Facebook
Uses browser_control internally with proper session handling
"""

import time
import asyncio
import platform
from pathlib import Path

_OS = platform.system()

# ─────────────────────────────────────────────
# LOGIN DETECTION
# ─────────────────────────────────────────────

# Signs that you ARE logged in to each platform
_LOGIN_INDICATORS = {
    "instagram": [
        "instagram.com/direct",
        "Create new post",
        "instagram.com/explore",
        'aria-label="Home"',
        "home_icon",
        "Profile",
        "Messages",
        "Notifications",
    ],
    "twitter": [
        "Home timeline",
        "x.com/home",
        "twitter.com/home",
        "What is happening",
        "Post",
        "For you",
        "Following",
    ],
    "x": [
        "x.com/home",
        "What is happening",
        "For you",
        "Following",
    ],
    "linkedin": [
        "linkedin.com/feed",
        "Start a post",
        "My Network",
        "Jobs",
        "Messaging",
    ],
    "facebook": [
        "facebook.com/home",
        "What's on your mind",
        "Create Post",
        "Watch",
        "Marketplace",
    ],
}

# Login page signs (means NOT logged in)
_LOGOUT_INDICATORS = {
    "instagram": [
        "Log in",
        "Sign up",
        "Log into Instagram",
        "phone number, username, or email",
    ],
    "twitter": [
        "Sign in to X",
        "Sign in",
        "Create account",
        "Phone, email, or username",
    ],
    "x": [
        "Sign in to X",
        "Sign in",
        "Create account",
    ],
    "linkedin": [
        "Join now",
        "Sign in",
        "Email or phone",
        "linkedin.com/login",
    ],
    "facebook": [
        "Log in to Facebook",
        "Create new account",
        "Forgotten password",
        "facebook.com/login",
    ],
}

# Login URLs for each platform
_LOGIN_URLS = {
    "instagram": "https://www.instagram.com/accounts/login/",
    "twitter":   "https://x.com/login",
    "x":         "https://x.com/login",
    "linkedin":  "https://www.linkedin.com/login",
    "facebook":  "https://www.facebook.com/login/",
}

# Home URLs for each platform
_HOME_URLS = {
    "instagram": "https://www.instagram.com",
    "twitter":   "https://x.com/home",
    "x":         "https://x.com/home",
    "linkedin":  "https://www.linkedin.com/feed/",
    "facebook":  "https://www.facebook.com",
}


async def _check_login_status(sess, platform: str) -> dict:
    """
    Navigate to the platform and check if user is logged in.
    Returns:
        {
            "logged_in": True/False,
            "message":   "explanation"
        }
    """
    home_url = _HOME_URLS.get(platform, "")
    if not home_url:
        return {"logged_in": False, "message": f"Unknown platform: {platform}"}

    try:
        # Go to homepage
        page = await sess._get_page()
        await page.goto(home_url, wait_until="domcontentloaded", timeout=15000)
        await asyncio.sleep(3)

        # Get current URL and page text
        current_url = page.url.lower()
        page_text   = await page.inner_text("body")
        page_lower  = page_text.lower()

        # Check for logout indicators first
        logout_signs = _LOGOUT_INDICATORS.get(platform, [])
        for sign in logout_signs:
            if sign.lower() in page_lower or sign.lower() in current_url:
                return {
                    "logged_in": False,
                    "message":   (
                        f"You are not logged in to {platform.capitalize()}, sir. "
                        f"Please log in to {platform.capitalize()} in your browser first, "
                        f"then ask me again."
                    )
                }

        # Check for login indicators
        login_signs = _LOGIN_INDICATORS.get(platform, [])
        for sign in login_signs:
            if sign.lower() in page_lower or sign.lower() in current_url:
                return {
                    "logged_in": True,
                    "message":   f"Logged in to {platform.capitalize()}."
                }

        # Ambiguous - check URL
        if "login" in current_url or "signin" in current_url or "accounts/login" in current_url:
            return {
                "logged_in": False,
                "message":   (
                    f"You are not logged in to {platform.capitalize()}, sir. "
                    f"Please open {platform.capitalize()} in Brave browser, "
                    f"log in manually, then ask me again."
                )
            }

        # If we got to the home page without login page, assume logged in
        return {
            "logged_in": True,
            "message":   f"Logged in to {platform.capitalize()}."
        }

    except Exception as e:
        return {
            "logged_in": False,
            "message":   f"Could not check login status: {e}"
        }

# ─────────────────────────────────────────────
# BROWSER HELPER
# ─────────────────────────────────────────────

def _run_social(platform_name: str, coro_fn, browser: str = "brave",
                timeout: int = 30, player=None) -> str:
    """
    Safely run a social media coroutine using browser_control.
    Handles session creation, errors and reconnection.
    """
    from actions.browser_control import _registry

    try:
        sess = _registry.get(browser)

        # Make sure session is alive
        if not sess._loop or not sess._thread or not sess._thread.is_alive():
            print(f"[Social] Restarting browser session for {browser}")
            sess.start()
            time.sleep(2)

        result = sess.run(coro_fn(sess), timeout=timeout)
        return result

    except Exception as e:
        error_str = str(e)

        # Session died - restart it
        if any(x in error_str for x in [
            "closed", "Target page", "Browser has been",
            "Connection refused", "not connected"
        ]):
            print(f"[Social] Session died, restarting...")
            try:
                from actions.browser_control import _registry, _BrowserSession
                # Remove old session
                with _registry._lock:
                    old = _registry._sessions.pop(browser, None)
                    if old:
                        try:
                            old.close()
                        except Exception:
                            pass

                # Create fresh session
                time.sleep(1)
                sess = _registry.get(browser)
                time.sleep(2)

                result = sess.run(coro_fn(sess), timeout=timeout)
                return result

            except Exception as e2:
                return f"Could not restart browser session: {e2}"

        return f"{platform_name} error: {e}"


# ─────────────────────────────────────────────
# INSTAGRAM COROUTINES
# ─────────────────────────────────────────────

async def _ig_open(sess) -> str:
    await sess.go_to("https://www.instagram.com")
    await asyncio.sleep(3)
    return "Instagram opened."


async def _ig_notifications(sess) -> str:
    await sess.go_to("https://www.instagram.com")
    await asyncio.sleep(3)

    # Click notifications bell
    try:
        page = await sess._get_page()
        # Try clicking the notifications icon
        for selector in [
            'a[href="/notifications/"]',
            '[aria-label="Notifications"]',
            'svg[aria-label="Notifications"]',
        ]:
            try:
                await page.click(selector, timeout=3000)
                await asyncio.sleep(2)
                break
            except Exception:
                continue
    except Exception:
        pass

    await asyncio.sleep(2)
    page = await sess._get_page()
    try:
        text  = await page.inner_text("body")
        lines = [
            l.strip() for l in text.split("\n")
            if l.strip() and len(l.strip()) > 5
        ][:25]
        if lines:
            return "Instagram notifications:\n" + "\n".join(lines)
        return "No notifications found or not logged in."
    except Exception as e:
        return f"Could not read notifications: {e}"


async def _ig_dms(sess) -> str:
    await sess.go_to("https://www.instagram.com/direct/inbox/")
    await asyncio.sleep(4)

    page = await sess._get_page()
    try:
        text  = await page.inner_text("body")
        lines = [
            l.strip() for l in text.split("\n")
            if l.strip() and len(l.strip()) > 3
        ][:20]
        if lines:
            return "Instagram DMs:\n" + "\n".join(lines)
        return "No DMs found or not logged in to Instagram."
    except Exception as e:
        return f"Could not read DMs: {e}"


async def _ig_post(sess, caption: str) -> str:
    await sess.go_to("https://www.instagram.com")
    await asyncio.sleep(3)

    page = await sess._get_page()
    try:
        for selector in [
            'svg[aria-label="New post"]',
            '[aria-label="New post"]',
            'a[href="/create/style/"]',
        ]:
            try:
                await page.click(selector, timeout=3000)
                await asyncio.sleep(2)
                return (
                    "Instagram new post dialog opened. "
                    "Please select your image to complete the post."
                )
            except Exception:
                continue
    except Exception:
        pass

    return (
        "Instagram is open. Please click the + button to create a new post. "
        f"Your caption: {caption}"
    )


async def _ig_follow(sess, username: str) -> str:
    await sess.go_to(f"https://www.instagram.com/{username}/")
    await asyncio.sleep(3)

    page = await sess._get_page()
    try:
        for selector in [
            'button:has-text("Follow")',
            '[aria-label="Follow"]',
        ]:
            try:
                await page.click(selector, timeout=3000)
                await asyncio.sleep(1)
                return f"Followed @{username} on Instagram."
            except Exception:
                continue
        return f"Opened @{username} profile. Please click Follow manually."
    except Exception as e:
        return f"Could not follow @{username}: {e}"


async def _ig_like(sess, url: str) -> str:
    await sess.go_to(url)
    await asyncio.sleep(3)

    page = await sess._get_page()
    try:
        for selector in [
            'svg[aria-label="Like"]',
            '[aria-label="Like"]',
        ]:
            try:
                await page.click(selector, timeout=3000)
                await asyncio.sleep(1)
                return f"Liked post: {url}"
            except Exception:
                continue
        return f"Post opened at {url}. Please click Like manually."
    except Exception as e:
        return f"Could not like post: {e}"


async def _ig_search(sess, query: str) -> str:
    await sess.go_to("https://www.instagram.com/explore/search/")
    await asyncio.sleep(3)

    page = await sess._get_page()
    try:
        # Type in search box
        for selector in [
            'input[placeholder="Search"]',
            'input[aria-label="Search input"]',
            '[role="searchbox"]',
        ]:
            try:
                await page.click(selector, timeout=3000)
                await page.type(selector, query, delay=50)
                await asyncio.sleep(2)
                break
            except Exception:
                continue

        text  = await page.inner_text("body")
        lines = [
            l.strip() for l in text.split("\n")
            if l.strip() and len(l.strip()) > 3
        ][:15]
        return f"Instagram search '{query}':\n" + "\n".join(lines)
    except Exception as e:
        return f"Search failed: {e}"


async def _ig_comment(sess, url: str, comment: str) -> str:
    await sess.go_to(url)
    await asyncio.sleep(3)

    page = await sess._get_page()
    try:
        for selector in [
            'textarea[aria-label="Add a comment…"]',
            'textarea[placeholder="Add a comment…"]',
        ]:
            try:
                await page.click(selector, timeout=3000)
                await page.type(selector, comment, delay=50)
                await asyncio.sleep(1)
                await page.keyboard.press("Enter")
                return f"Comment posted: {comment}"
            except Exception:
                continue
        return "Could not find comment box. Please comment manually."
    except Exception as e:
        return f"Could not post comment: {e}"


# ─────────────────────────────────────────────
# TWITTER / X COROUTINES
# ─────────────────────────────────────────────

async def _tw_open(sess) -> str:
    await sess.go_to("https://x.com")
    await asyncio.sleep(3)
    return "Twitter/X opened."


async def _tw_notifications(sess) -> str:
    await sess.go_to("https://x.com/notifications")
    await asyncio.sleep(4)
    page = await sess._get_page()
    try:
        text  = await page.inner_text("body")
        lines = [
            l.strip() for l in text.split("\n")
            if l.strip() and len(l.strip()) > 5
        ][:25]
        return "Twitter notifications:\n" + "\n".join(lines)
    except Exception as e:
        return f"Could not read notifications: {e}"


async def _tw_dms(sess) -> str:
    await sess.go_to("https://x.com/messages")
    await asyncio.sleep(4)
    page = await sess._get_page()
    try:
        text  = await page.inner_text("body")
        lines = [
            l.strip() for l in text.split("\n")
            if l.strip() and len(l.strip()) > 3
        ][:20]
        return "Twitter DMs:\n" + "\n".join(lines)
    except Exception as e:
        return f"Could not read DMs: {e}"


async def _tw_tweet(sess, content: str) -> str:
    await sess.go_to("https://x.com/compose/tweet")
    await asyncio.sleep(3)
    page = await sess._get_page()
    try:
        for selector in [
            '[data-testid="tweetTextarea_0"]',
            'div[aria-label="Tweet text"]',
            'div[contenteditable="true"]',
        ]:
            try:
                await page.click(selector, timeout=3000)
                await page.type(selector, content, delay=50)
                await asyncio.sleep(1)

                # Click tweet button
                for btn in [
                    '[data-testid="tweetButtonInline"]',
                    '[data-testid="tweetButton"]',
                    'div[aria-label="Tweet"]',
                ]:
                    try:
                        await page.click(btn, timeout=3000)
                        return f"Tweet posted: {content[:80]}"
                    except Exception:
                        continue
                return f"Tweet typed. Please click Post to publish: {content[:80]}"
            except Exception:
                continue
        return f"Could not find tweet box. Tweet content: {content}"
    except Exception as e:
        return f"Tweet failed: {e}"


async def _tw_search(sess, query: str) -> str:
    url = f"https://x.com/search?q={query.replace(' ', '+')}&src=typed_query"
    await sess.go_to(url)
    await asyncio.sleep(4)
    page = await sess._get_page()
    try:
        text  = await page.inner_text("body")
        lines = [
            l.strip() for l in text.split("\n")
            if l.strip() and len(l.strip()) > 10
        ][:20]
        return f"Twitter search '{query}':\n" + "\n".join(lines)
    except Exception as e:
        return f"Search failed: {e}"


# ─────────────────────────────────────────────
# LINKEDIN COROUTINES
# ─────────────────────────────────────────────

async def _li_open(sess) -> str:
    await sess.go_to("https://www.linkedin.com/feed/")
    await asyncio.sleep(3)
    return "LinkedIn opened."


async def _li_notifications(sess) -> str:
    await sess.go_to("https://www.linkedin.com/notifications/")
    await asyncio.sleep(4)
    page = await sess._get_page()
    try:
        text  = await page.inner_text("body")
        lines = [
            l.strip() for l in text.split("\n")
            if l.strip() and len(l.strip()) > 5
        ][:25]
        return "LinkedIn notifications:\n" + "\n".join(lines)
    except Exception as e:
        return f"Could not read notifications: {e}"


async def _li_messages(sess) -> str:
    await sess.go_to("https://www.linkedin.com/messaging/")
    await asyncio.sleep(4)
    page = await sess._get_page()
    try:
        text  = await page.inner_text("body")
        lines = [
            l.strip() for l in text.split("\n")
            if l.strip() and len(l.strip()) > 3
        ][:20]
        return "LinkedIn messages:\n" + "\n".join(lines)
    except Exception as e:
        return f"Could not read messages: {e}"


async def _li_post(sess, content: str) -> str:
    await sess.go_to("https://www.linkedin.com/feed/")
    await asyncio.sleep(3)
    page = await sess._get_page()
    try:
        for selector in [
            'button[aria-label="Start a post"]',
            '.share-box-feed-entry__trigger',
        ]:
            try:
                await page.click(selector, timeout=3000)
                await asyncio.sleep(2)

                for txt_selector in [
                    'div[aria-label="Text editor for creating content"]',
                    'div[contenteditable="true"]',
                    '.ql-editor',
                ]:
                    try:
                        await page.click(txt_selector, timeout=3000)
                        await page.type(txt_selector, content, delay=50)
                        return (
                            f"LinkedIn post drafted: {content[:80]}. "
                            "Please click Post to publish."
                        )
                    except Exception:
                        continue
            except Exception:
                continue
        return (
            "LinkedIn is open. Please click 'Start a post' to create your post. "
            f"Content: {content}"
        )
    except Exception as e:
        return f"LinkedIn post failed: {e}"


# ─────────────────────────────────────────────
# FACEBOOK COROUTINES
# ─────────────────────────────────────────────

async def _fb_open(sess) -> str:
    await sess.go_to("https://www.facebook.com")
    await asyncio.sleep(3)
    return "Facebook opened."


async def _fb_notifications(sess) -> str:
    await sess.go_to("https://www.facebook.com/notifications")
    await asyncio.sleep(4)
    page = await sess._get_page()
    try:
        text  = await page.inner_text("body")
        lines = [
            l.strip() for l in text.split("\n")
            if l.strip() and len(l.strip()) > 5
        ][:25]
        return "Facebook notifications:\n" + "\n".join(lines)
    except Exception as e:
        return f"Could not read notifications: {e}"


async def _fb_messages(sess) -> str:
    await sess.go_to("https://www.facebook.com/messages")
    await asyncio.sleep(4)
    page = await sess._get_page()
    try:
        text  = await page.inner_text("body")
        lines = [
            l.strip() for l in text.split("\n")
            if l.strip() and len(l.strip()) > 3
        ][:20]
        return "Facebook messages:\n" + "\n".join(lines)
    except Exception as e:
        return f"Could not read messages: {e}"


# ─────────────────────────────────────────────
# ROUTING TABLE
# ─────────────────────────────────────────────

_ROUTES = {
    "instagram": {
        "open":          _ig_open,
        "notifications": _ig_notifications,
        "notify":        _ig_notifications,
        "dms":           _ig_dms,
        "messages":      _ig_dms,
        "post":          None,  # needs extra args
        "follow":        None,  # needs extra args
        "like":          None,  # needs extra args
        "search":        None,  # needs extra args
        "comment":       None,  # needs extra args
    },
    "twitter": {
        "open":          _tw_open,
        "notifications": _tw_notifications,
        "notify":        _tw_notifications,
        "dms":           _tw_dms,
        "messages":      _tw_dms,
        "post":          None,
        "tweet":         None,
        "search":        None,
    },
    "x": {
        "open":          _tw_open,
        "notifications": _tw_notifications,
        "dms":           _tw_dms,
        "post":          None,
        "tweet":         None,
        "search":        None,
    },
    "linkedin": {
        "open":          _li_open,
        "notifications": _li_notifications,
        "notify":        _li_notifications,
        "messages":      _li_messages,
        "dms":           _li_messages,
        "post":          None,
    },
    "facebook": {
        "open":          _fb_open,
        "notifications": _fb_notifications,
        "notify":        _fb_notifications,
        "messages":      _fb_messages,
        "dms":           _fb_messages,
    },
}


# ─────────────────────────────────────────────
# MAIN AGENT
# ─────────────────────────────────────────────

def social_agent(
    parameters: dict,
    player=None,
    speak=None,
) -> str:
    params   = parameters or {}
    platform = params.get("platform", "instagram").lower().strip()
    action   = params.get("action", "open").lower().strip()
    browser  = params.get("browser", "brave").lower().strip()
    content  = params.get("content", "").strip()
    username = params.get("username", "").strip()
    url      = params.get("url", "").strip()
    query    = params.get("query", "").strip()

    if player:
        player.write_log(f"[Social] {platform} → {action}")

    print(f"[Social] {platform} → {action}")

    platform_routes = _ROUTES.get(platform)
    if not platform_routes:
        return (
            f"Unknown platform: '{platform}'. "
            "Supported: instagram, twitter, x, linkedin, facebook"
        )

    try:
        from actions.browser_control import _registry
        sess = _registry.get(browser)

        # Restart session if dead
        if not sess._thread or not sess._thread.is_alive():
            sess.start()
            time.sleep(2)

        # ── CHECK LOGIN STATUS FIRST ──────────────
        # Skip login check only for "open" action
        if action != "open":
            if player:
                player.write_log(f"[Social] Checking login status for {platform}...")

            login_status = sess.run(
                _check_login_status(sess, platform),
                timeout=20
            )

            if not login_status["logged_in"]:
                msg = login_status["message"]
                print(f"[Social] ❌ Not logged in: {msg}")
                if speak:
                    speak(msg)
                if player:
                    player.write_log(f"[Social] Not logged in to {platform}")
                return msg

            print(f"[Social] ✅ Logged in to {platform}")

                    # ── Check Login Action ────────────────────
        if action == "check_login":
            login_status = sess.run(
                _check_login_status(sess, platform),
                timeout=20
            )
            msg = login_status["message"]
            if speak:
                speak(msg)
            return msg

        # ── Instagram special actions ─────────────
        if platform == "instagram":
            if action == "post":
                return _run_social(
                    platform, lambda s: _ig_post(s, content),
                    browser, player=player
                )
            elif action == "follow":
                if not username:
                    return "Please provide a username to follow, sir."
                return _run_social(
                    platform, lambda s: _ig_follow(s, username),
                    browser, player=player
                )
            elif action == "like":
                if not url:
                    return "Please provide a post URL to like, sir."
                return _run_social(
                    platform, lambda s: _ig_like(s, url),
                    browser, player=player
                )
            elif action == "search":
                if not query:
                    return "Please provide a search query, sir."
                return _run_social(
                    platform, lambda s: _ig_search(s, query),
                    browser, player=player
                )
            elif action == "comment":
                if not url or not content:
                    return "Please provide a post URL and comment text, sir."
                return _run_social(
                    platform, lambda s: _ig_comment(s, url, content),
                    browser, player=player
                )

        # ── Twitter special actions ───────────────
        if platform in ("twitter", "x"):
            if action in ("post", "tweet"):
                if not content:
                    return "Please provide tweet content, sir."
                return _run_social(
                    platform, lambda s: _tw_tweet(s, content),
                    browser, player=player
                )
            elif action == "search":
                if not query:
                    return "Please provide a search query, sir."
                return _run_social(
                    platform, lambda s: _tw_search(s, query),
                    browser, player=player
                )

        # ── LinkedIn special actions ──────────────
        if platform == "linkedin":
            if action == "post":
                if not content:
                    return "Please provide post content, sir."
                return _run_social(
                    platform, lambda s: _li_post(s, content),
                    browser, player=player
                )

        # ── Standard routing ─────────────────────
        coro_fn = platform_routes.get(action)
        if coro_fn is None:
            return (
                f"Unknown action '{action}' for {platform}. "
                f"Available: {', '.join(platform_routes.keys())}"
            )

        result = _run_social(platform, coro_fn, browser, player=player)

        if speak and result and len(result) < 300:
            speak(result)

        return result

    except Exception as e:
        print(f"[Social] Error: {e}")
        return f"Social agent error: {e}"