"""
email_browser.py — VINCEVISION browser-based email backend
──────────────────────────────────────────────────────────
Sign in to your OWN mailbox in a real browser window using your normal
email address + password (and 2FA), exactly like you would manually.
The session is then saved locally and reused — no app passwords, no
IMAP/SMTP setup, no "long phrase tokens".

PRIVACY / SECURITY MODEL
  * You type your password directly into the provider's real login page.
    This tool NEVER reads, logs, stores, or transmits your password.
  * Only the browser's own session profile (cookies) is persisted, in
    ``browser_profiles/email/<provider>/<account>/`` — which is gitignored,
    so it never leaves your machine and is never pushed to GitHub.
  * 2FA / captcha / "confirm it's you" prompts are completed by YOU in the
    visible window. Nothing is bypassed.

Gmail is fully supported (login / read / search / send). Outlook is
supported for login / read / send. Other providers can save a login
session; automated read/send for them falls back to a clear message.
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


PROFILES_ROOT = _base_dir() / "browser_profiles" / "email"
LOGIN_TIMEOUT = 300  # seconds to wait for the user to finish logging in


PROVIDERS = {
    "gmail": {
        "name":       "Gmail",
        "login_url":  "https://mail.google.com/",
        "inbox_url":  "https://mail.google.com/mail/u/0/#inbox",
        "search_url": "https://mail.google.com/mail/u/0/#search/{q}",
        "domains":    ("gmail.com", "googlemail.com"),
        "read_send":  True,
    },
    "outlook": {
        "name":       "Outlook",
        "login_url":  "https://outlook.live.com/mail/0/",
        "inbox_url":  "https://outlook.live.com/mail/0/inbox",
        "search_url": "https://outlook.live.com/mail/0/search?q={q}",
        "domains":    ("outlook.com", "hotmail.com", "live.com", "office365.com"),
        "read_send":  True,
    },
    "yahoo": {
        "name":       "Yahoo Mail",
        "login_url":  "https://mail.yahoo.com/",
        "inbox_url":  "https://mail.yahoo.com/d/folders/1",
        "search_url": "https://mail.yahoo.com/d/search/keyword={q}",
        "domains":    ("yahoo.com", "ymail.com"),
        "read_send":  False,
    },
}


# ════════════════════════════════════════════════════════════════
# Pure helpers (unit-tested offline)
# ════════════════════════════════════════════════════════════════

def detect_provider(email_or_provider: str) -> str:
    """Map an email address or provider name to a provider key."""
    val = (email_or_provider or "").strip().lower()
    if val in PROVIDERS:
        return val
    if "@" in val:
        domain = val.split("@", 1)[1]
        for key, spec in PROVIDERS.items():
            if domain in spec["domains"]:
                return key
        return "custom"
    return ""


def profile_dir(provider: str, email: str) -> Path:
    """Per-account persistent profile path (gitignored)."""
    slug = re.sub(r"[^a-z0-9]+", "_", (email or "default").lower()).strip("_") or "default"
    return PROFILES_ROOT / provider / slug


def is_logged_in_url(provider: str, url: str) -> bool:
    """Decide from the URL whether we're past the login screen."""
    url = url or ""
    if provider == "gmail":
        return url.startswith("https://mail.google.com/mail")
    if provider == "outlook":
        return any(h in url for h in (
            "outlook.live.com/mail", "outlook.office.com/mail", "outlook.office365.com/mail",
        ))
    if provider == "yahoo":
        return "mail.yahoo.com" in url and "login" not in url
    return False


def format_emails(emails: list, max_body: int = 160) -> str:
    if not emails:
        return "No emails found, sir."
    lines = []
    for i, em in enumerate(emails, 1):
        frm = (em.get("from") or "?").split("<")[0].strip()
        subj = em.get("subject") or "(no subject)"
        body = (em.get("body") or "").strip().replace("\n", " ")
        if len(body) > max_body:
            body = body[:max_body] + "…"
        flag = "🔵 " if em.get("unread") else "   "
        lines.append(f"{flag}{i}. {frm} — {subj}\n      {body}")
    return "\n".join(lines)


def _log(player, msg):
    print(f"[EmailBrowser] {msg}")
    if player:
        try:
            player.write_log(f"[Email] {msg}"[:200])
        except Exception:
            pass


def _speak(speak, msg):
    if speak:
        try:
            speak(msg)
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════
# Playwright plumbing (lazy imports so the module loads without it)
# ════════════════════════════════════════════════════════════════

def _launch_kwargs(headless: bool):
    args = [
        "--no-sandbox", "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled", "--start-maximized",
    ]
    env = os.environ.copy()
    # Reuse JARVIS's browser session/user handling when available (root → real user)
    try:
        from actions.browser_control import _get_args, _build_env_for_user, _get_real_user
        user, uid = _get_real_user()
        args = _get_args(headless)
        env = _build_env_for_user(user, uid)
    except Exception:
        pass
    return args, env


def _launch_context(pw, pdir: Path, headless: bool):
    """Launch a persistent context, preferring installed Chrome/Edge."""
    pdir.mkdir(parents=True, exist_ok=True)
    args, env = _launch_kwargs(headless)
    last_err = None
    for channel in ("chrome", "msedge", None):
        try:
            kw = dict(
                user_data_dir=str(pdir), headless=headless,
                args=args, env=env, viewport=None, no_viewport=True,
            )
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
# Gmail operations
# ════════════════════════════════════════════════════════════════

def _gmail_read(page, count, unread_only):
    rows = page.query_selector_all("tr.zA")
    out = []
    for r in rows:
        cls = r.get_attribute("class") or ""
        unread = "zE" in cls
        if unread_only and not unread:
            continue
        sender_el = r.query_selector(".zF")
        name = sender_el.get_attribute("name") if sender_el else ""
        addr = sender_el.get_attribute("email") if sender_el else ""
        subj_el = r.query_selector(".bogt, .bqe")
        subject = subj_el.inner_text().strip() if subj_el else ""
        snip_el = r.query_selector(".y2")
        snippet = snip_el.inner_text().strip() if snip_el else ""
        out.append({
            "from": f"{name} <{addr}>".strip(),
            "subject": subject, "body": snippet, "unread": unread,
        })
        if len(out) >= count:
            break
    return out


def _gmail_send(page, to, subject, body):
    compose = page.query_selector('div[gh="cm"]')
    if not compose:
        compose = page.get_by_text("Compose", exact=False).first
    compose.click()
    page.wait_for_selector('input[name="subjectbox"]', timeout=15000)

    to_el = (page.query_selector('input[aria-label="To recipients"]')
             or page.query_selector('textarea[name="to"]'))
    if to_el:
        to_el.click()
        to_el.type(to, delay=20)
        page.keyboard.press("Enter")
    page.wait_for_timeout(400)

    subj = page.query_selector('input[name="subjectbox"]')
    if subj:
        subj.fill(subject)
    body_el = page.query_selector('div[aria-label="Message Body"]')
    if body_el:
        body_el.click()
        body_el.type(body, delay=5)

    send = (page.query_selector('div[aria-label="Send"]')
            or page.query_selector('div[data-tooltip^="Send"]'))
    if not send:
        raise RuntimeError("Send button not found")
    send.click()
    page.wait_for_timeout(2500)


# ════════════════════════════════════════════════════════════════
# Outlook operations (best-effort)
# ════════════════════════════════════════════════════════════════

def _outlook_read(page, count, unread_only):
    rows = page.query_selector_all('div[role="option"], div[data-convid]')
    out = []
    for r in rows:
        text = (r.inner_text() or "").strip().replace("\n", " ")
        if not text:
            continue
        unread = "unread" in (r.get_attribute("aria-label") or "").lower()
        if unread_only and not unread:
            continue
        out.append({"from": "", "subject": text[:120], "body": text[:200], "unread": unread})
        if len(out) >= count:
            break
    return out


def _outlook_send(page, to, subject, body):
    new = (page.query_selector('button[aria-label="New mail"]')
           or page.get_by_text("New mail", exact=False).first)
    new.click()
    page.wait_for_timeout(1500)
    to_el = page.query_selector('input[aria-label="To"]')
    if to_el:
        to_el.click(); to_el.type(to, delay=20); page.keyboard.press("Enter")
    subj = page.query_selector('input[aria-label="Subject"]')
    if subj:
        subj.fill(subject)
    body_el = page.query_selector('div[aria-label="Message body"]')
    if body_el:
        body_el.click(); body_el.type(body, delay=5)
    send = page.query_selector('button[aria-label="Send"]')
    if not send:
        raise RuntimeError("Send button not found")
    send.click()
    page.wait_for_timeout(2500)


# ════════════════════════════════════════════════════════════════
# High-level actions
# ════════════════════════════════════════════════════════════════

def _resolve_account(params) -> tuple:
    """Return (provider, email). Provider may be given or detected from email."""
    email = (params.get("email") or "").strip()
    provider = (params.get("provider") or "").strip().lower()
    if not provider:
        provider = detect_provider(email)
    if not provider and email:
        provider = "custom"
    return provider, email


def _do_login(provider, email, player, speak) -> str:
    if provider not in PROVIDERS:
        return ("I can save a browser login for Gmail, Outlook, or Yahoo. "
                "Tell me the provider or email address, sir.")
    spec = PROVIDERS[provider]
    pdir = profile_dir(provider, email)
    from playwright.sync_api import sync_playwright

    _log(player, f"Opening {spec['name']} login window…")
    _speak(speak,
           f"Opening {spec['name']}. Please sign in with your normal email and password. "
           "I never see your password — complete any two-step prompt yourself.")
    try:
        with sync_playwright() as pw:
            ctx = _launch_context(pw, pdir, headless=False)
            page = _first_page(ctx)
            try:
                _goto(page, spec["login_url"])
            except Exception as e:
                ctx.close()
                return (f"Couldn't open the login page: {e}. If JARVIS is running as root, "
                        "run it as your desktop user so the browser window can appear.")
            deadline = time.time() + LOGIN_TIMEOUT
            ok = False
            while time.time() < deadline:
                try:
                    if is_logged_in_url(provider, page.url):
                        page.wait_for_timeout(2500)
                        if is_logged_in_url(provider, page.url):
                            ok = True
                            break
                except Exception:
                    break  # window closed
                time.sleep(2)
            ctx.close()
    except Exception as e:
        return (f"Browser login failed: {e}. If JARVIS runs as root, try running it as your "
                "desktop user (e.g. `sudo -u <your-user> python3 main.py`) so the window can open.")

    if ok:
        _log(player, f"{spec['name']} session saved.")
        _speak(speak, f"{spec['name']} is connected, sir. Your session is saved.")
        return (f"✅ {spec['name']} connected. Session saved locally "
                f"(browser_profiles/email/{provider}/…). "
                "You can now ask me to check, search, or send email.")
    return ("Login wasn't completed in time, sir. Say 'email login' to try again — "
            "the window stays open for five minutes.")


def _with_session(provider, email, headless, fn, player):
    """Run fn(page) inside a saved session; handle missing/expired login."""
    pdir = profile_dir(provider, email)
    if not pdir.exists():
        return None, (f"No saved {PROVIDERS.get(provider, {}).get('name', provider)} session. "
                      "Say 'email login' first, sir.")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx = _launch_context(pw, pdir, headless=headless)
        page = _first_page(ctx)
        try:
            result = fn(page)
        finally:
            ctx.close()
    return result, None


def _do_read(provider, email, count, unread_only, player, speak) -> str:
    spec = PROVIDERS.get(provider)
    if not spec or not spec["read_send"]:
        return f"Automated reading isn't available for {provider}; the login session is saved though."

    def work(page):
        _goto(page, spec["inbox_url"])
        if not is_logged_in_url(provider, page.url):
            return "EXPIRED"
        page.wait_for_timeout(2000)
        if provider == "gmail":
            return _gmail_read(page, count, unread_only)
        return _outlook_read(page, count, unread_only)

    try:
        result, err = _with_session(provider, email, True, work, player)
    except Exception as e:
        return f"Couldn't read the inbox: {e}"
    if err:
        return err
    if result == "EXPIRED":
        return "Your session expired, sir. Say 'email login' to sign in again."
    if not result:
        msg = "No unread emails, sir." if unread_only else "Inbox is empty, sir."
        _speak(speak, msg)
        return msg
    _speak(speak, f"You have {len(result)} email{'s' if len(result) != 1 else ''}, sir.")
    return format_emails(result)


def _do_search(provider, email, query, count, player, speak) -> str:
    spec = PROVIDERS.get(provider)
    if not spec or not spec["read_send"]:
        return f"Automated search isn't available for {provider}."
    from urllib.parse import quote

    def work(page):
        _goto(page, spec["search_url"].format(q=quote(query)))
        if not is_logged_in_url(provider, page.url):
            return "EXPIRED"
        page.wait_for_timeout(2000)
        if provider == "gmail":
            return _gmail_read(page, count, False)
        return _outlook_read(page, count, False)

    try:
        result, err = _with_session(provider, email, True, work, player)
    except Exception as e:
        return f"Search failed: {e}"
    if err:
        return err
    if result == "EXPIRED":
        return "Your session expired, sir. Say 'email login' to sign in again."
    if not result:
        return f"No emails matching '{query}', sir."
    _speak(speak, f"Found {len(result)} emails matching {query}.")
    return format_emails(result)


def _do_send(provider, email, to, subject, body, player, speak) -> str:
    spec = PROVIDERS.get(provider)
    if not spec or not spec["read_send"]:
        return f"Automated sending isn't available for {provider}."
    if not to:
        return "❌ Please specify a recipient, sir."
    if not body:
        return "❌ Please provide a message body, sir."
    subject = subject or "Message from VINCEVISION"

    def work(page):
        _goto(page, spec["inbox_url"])
        if not is_logged_in_url(provider, page.url):
            return "EXPIRED"
        if provider == "gmail":
            _gmail_send(page, to, subject, body)
        else:
            _outlook_send(page, to, subject, body)
        return "SENT"

    try:
        result, err = _with_session(provider, email, True, work, player)
    except Exception as e:
        return f"Couldn't send the email: {e}"
    if err:
        return err
    if result == "EXPIRED":
        return "Your session expired, sir. Say 'email login' to sign in again."
    _speak(speak, f"Email sent to {to}, sir.")
    return f"✅ Email sent to {to}."


def _do_status(provider, email, player) -> str:
    pdir = profile_dir(provider, email)
    if not pdir.exists():
        return f"Not connected to {PROVIDERS.get(provider, {}).get('name', provider)}. Say 'email login'."

    def work(page):
        _goto(page, PROVIDERS[provider]["inbox_url"])
        return is_logged_in_url(provider, page.url)

    try:
        result, err = _with_session(provider, email, True, work, player)
    except Exception as e:
        return f"Status check failed: {e}"
    if err:
        return err
    name = PROVIDERS.get(provider, {}).get("name", provider)
    return f"✅ {name} session is active." if result else f"{name} session expired — say 'email login'."


def _do_logout(provider, email, player) -> str:
    pdir = profile_dir(provider, email)
    if pdir.exists():
        shutil.rmtree(pdir, ignore_errors=True)
        _log(player, f"Removed {provider} session.")
        return f"✅ Signed out of {PROVIDERS.get(provider, {}).get('name', provider)}; session deleted."
    return "No saved session to remove, sir."


def _setup_text() -> str:
    return (
        "📧 Email — the easy way (no app passwords):\n"
        "  1. Say 'email login' (or 'email login myname@gmail.com').\n"
        "  2. A browser window opens — sign in with your normal email + password,\n"
        "     and complete any 2FA prompt yourself. I never see your password.\n"
        "  3. The session is saved locally. Then just ask:\n"
        "     • 'check my email'   • 'search email for invoice'\n"
        "     • 'send an email to bob@x.com subject Hi body …'\n"
        "Works with Gmail and Outlook. Sessions live in browser_profiles/ (never pushed).\n"
        "Prefer the old IMAP way? Pass backend='imap'."
    )


# ════════════════════════════════════════════════════════════════
# Entry point
# ════════════════════════════════════════════════════════════════

def email_browser_agent(parameters: dict, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "check")).lower().strip()

    if action in ("setup", "help", "instructions"):
        return _setup_text()

    provider, email = _resolve_account(params)
    if not provider:
        # Fall back to a saved default profile if one exists
        if PROFILES_ROOT.exists():
            for prov in PROVIDERS:
                prov_dir = PROFILES_ROOT / prov
                if prov_dir.exists() and any(prov_dir.iterdir()):
                    provider = prov
                    subs = sorted(prov_dir.iterdir())
                    email = subs[0].name if subs else ""
                    break
    if not provider:
        return ("Which email account, sir? Say 'email login yourname@gmail.com' "
                "to connect one. No app password needed.")

    if action in ("login", "signin", "connect", "add_account"):
        return _do_login(provider, email, player, speak)
    if action in ("status", "whoami"):
        return _do_status(provider, email, player)
    if action in ("logout", "signout", "disconnect"):
        return _do_logout(provider, email, player)
    if action in ("check", "read", "inbox", "unread"):
        count = int(params.get("count", 10) or 10)
        unread_only = action == "unread" or params.get("unread_only", False)
        if isinstance(unread_only, str):
            unread_only = unread_only.lower() not in ("false", "0", "no")
        return _do_read(provider, email, count, bool(unread_only), player, speak)
    if action == "search":
        query = (params.get("keyword") or params.get("query") or "").strip()
        if not query:
            return "❌ Please provide a search keyword, sir."
        return _do_search(provider, email, query, int(params.get("count", 5) or 5), player, speak)
    if action == "send":
        return _do_send(provider, email,
                        (params.get("to") or "").strip(),
                        (params.get("subject") or "").strip(),
                        (params.get("body") or "").strip(),
                        player, speak)

    return (f"❌ Unknown email action '{action}'. "
            "Try: login, status, check, search, send, logout, setup.")
