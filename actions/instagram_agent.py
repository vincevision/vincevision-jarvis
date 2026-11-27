from __future__ import annotations

"""
Instagram Agent for JARVIS

Legitimate browser-control automation for the operator's own Instagram account.

Features:
- Login with saved session profile
- Manual 2FA / challenge handling
- Open feed/profile/reels/messages/notifications
- Search users/tags/places
- Follow / unfollow with confirmation
- Like / comment on a provided post URL
- Send a DM with confirmation
- Upload a photo/video post with confirmation
- Scroll feed like a normal user
- Logout

Safety notes:
- No CAPTCHA/2FA bypass.
- No credential stealing.
- No bulk spam/mass follow/mass DM loops.
- Destructive/public actions require confirm="INSTAGRAM CONFIRMED" unless dry_run=True.
"""

import json
import os
import random
import shutil
import time
import traceback
import webbrowser
from pathlib import Path
from typing import Optional


CONFIRM_TEXT = "INSTAGRAM CONFIRMED"
BASE_URL = "https://www.instagram.com"
CONFIG_PATH = Path("config") / "instagram.json"
PROFILE_DIR = Path("browser_profiles") / "instagram"


class InstagramAgentError(RuntimeError):
    pass


def _sleep(a: float = 0.8, b: float = 1.8):
    time.sleep(random.uniform(a, b))


def _log(player, msg: str):
    try:
        if player:
            player.write_log(msg)
    except Exception:
        pass


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_config(data: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _get_credential(parameters: dict, key: str) -> str:
    # Priority: explicit parameter -> environment -> local config file
    if parameters.get(key):
        return str(parameters[key])
    env_key = f"INSTAGRAM_{key.upper()}"
    if os.environ.get(env_key):
        return os.environ[env_key]
    cfg = _load_config()
    return str(cfg.get(key, ""))


def _setup_credentials(parameters: dict) -> str:
    # Browser-session login: no password is stored or typed by JARVIS.
    return (
        "No password needed. Say 'instagram login' — a browser window opens and you "
        "sign in yourself (username + password + 2FA). The session is saved locally in "
        "browser_profiles/instagram; JARVIS never sees or stores your password."
    )


def _require_confirm(parameters: dict, action: str) -> Optional[str]:
    dry_run = bool(parameters.get("dry_run", False))
    if dry_run:
        return f"Dry run: would execute Instagram action '{action}', but no public/account-changing action was performed."

    confirm = parameters.get("confirm", "")
    if confirm != CONFIRM_TEXT:
        return (
            f"Action '{action}' requires confirmation because it can change your account or publish content. "
            f"Call again with confirm='{CONFIRM_TEXT}'."
        )
    return None


def _find_browser_binary(browser: str) -> str | None:
    """Find a Chrome/Chromium-compatible browser binary on Linux."""
    explicit = os.environ.get("CHROME_BINARY") or os.environ.get("GOOGLE_CHROME_BIN")
    if explicit and Path(explicit).exists():
        return explicit

    browser = browser.lower().strip()
    candidates: list[str] = []

    if browser in ("chromium", "chromium-browser"):
        candidates = [
            "chromium",
            "chromium-browser",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
        ]
    elif browser in ("brave", "brave-browser"):
        candidates = [
            "brave-browser",
            "brave",
            "/usr/bin/brave-browser",
            "/opt/brave.com/brave/brave-browser",
        ]
    else:
        candidates = [
            "google-chrome",
            "google-chrome-stable",
            "chrome",
            "chromium",
            "chromium-browser",
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
        ]

    for c in candidates:
        found = shutil.which(c) if not c.startswith("/") else c
        if found and Path(found).exists():
            return found
    return None


def _clean_stale_profile_locks(profile_dir: Path):
    """
    Chrome leaves Singleton* files when it crashes. Those stale files can make
    Chrome exit immediately with SessionNotCreatedException.
    """
    try:
        for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
            p = profile_dir / name
            if p.exists() or p.is_symlink():
                try:
                    p.unlink()
                except Exception:
                    pass
    except Exception:
        pass


def _make_driver(parameters: dict, player=None):
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        from selenium.webdriver.chrome.service import Service as ChromeService
    except Exception as e:
        raise InstagramAgentError(
            "Selenium is not installed. Install it with: pip install selenium webdriver-manager"
        ) from e

    browser = str(parameters.get("browser", "chrome")).lower()
    headless = bool(parameters.get("headless", False))

    if browser not in ("chrome", "google-chrome", "chromium", "chromium-browser", "brave", "brave-browser"):
        raise InstagramAgentError("Supported browsers: chrome, chromium, brave.")

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    _clean_stale_profile_locks(PROFILE_DIR)

    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    chromedriver_log = log_dir / "instagram_chromedriver.log"

    options = ChromeOptions()

    binary = _find_browser_binary(browser)
    if binary:
        options.binary_location = binary
        _log(player, f"[IG] Using browser binary: {binary}")

    # Use a dedicated profile so your normal browser profile is not locked/corrupted.
    options.add_argument(f"--user-data-dir={PROFILE_DIR.resolve()}")
    options.add_argument("--profile-directory=Default")

    # Linux stability flags. These fix most 'Chrome instance exited' errors.
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--window-size=1366,900")
    options.add_argument("--remote-debugging-port=0")
    options.add_argument("--password-store=basic")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    if headless:
        # Headless login is more likely to trigger Instagram challenges.
        options.add_argument("--headless=new")

    last_error = None

    # Attempt 1: Selenium Manager. Best when selenium can find the matching driver.
    try:
        service = ChromeService(log_output=str(chromedriver_log))
        driver = webdriver.Chrome(service=service, options=options)
    except Exception as e:
        last_error = e
        _log(player, f"[IG] Selenium Manager Chrome start failed: {str(e)[:160]}")

        # Attempt 2: webdriver-manager downloaded driver.
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            service = ChromeService(ChromeDriverManager().install(), log_output=str(chromedriver_log))
            driver = webdriver.Chrome(service=service, options=options)
        except Exception as e2:
            last_error = e2
            _log(player, f"[IG] webdriver-manager Chrome start failed: {str(e2)[:160]}")

            # Attempt 3: fresh temporary profile in case the saved profile is locked/corrupt.
            try:
                import tempfile
                temp_profile = Path(tempfile.mkdtemp(prefix="jarvis_ig_chrome_"))
                options2 = ChromeOptions()
                if binary:
                    options2.binary_location = binary
                for arg in [
                    f"--user-data-dir={temp_profile}",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                    "--disable-notifications",
                    "--window-size=1366,900",
                    "--remote-debugging-port=0",
                    "--password-store=basic",
                    "--no-first-run",
                    "--no-default-browser-check",
                ]:
                    options2.add_argument(arg)
                if headless:
                    options2.add_argument("--headless=new")
                options2.add_experimental_option("excludeSwitches", ["enable-automation"])
                options2.add_experimental_option("useAutomationExtension", False)
                service = ChromeService(log_output=str(chromedriver_log))
                driver = webdriver.Chrome(service=service, options=options2)
                _log(player, "[IG] Started Chrome using a temporary profile. Login session will not persist.")
            except Exception as e3:
                last_error = e3
                raise InstagramAgentError(
                    "Could not start Chrome WebDriver. Common fixes:\n"
                    "1) Install/update Chrome or Chromium.\n"
                    "2) Run: pip install -U selenium webdriver-manager\n"
                    "3) Close all Chrome windows using the Instagram automation profile.\n"
                    "4) Delete stale locks: rm -f browser_profiles/instagram/Singleton*\n"
                    f"5) Check log: {chromedriver_log}\n"
                    f"Last error: {last_error}"
                ) from e3

    driver.implicitly_wait(4)

    # Anti-automation hint reduction. This is not a CAPTCHA/2FA bypass.
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            },
        )
    except Exception:
        pass

    return driver


def _find(driver, by, value, timeout=15):
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    return WebDriverWait(driver, timeout).until(EC.presence_of_element_located((by, value)))


def _click_if_present(driver, selectors: list[str], timeout: float = 2.0) -> bool:
    from selenium.webdriver.common.by import By
    end = time.time() + timeout
    while time.time() < end:
        for css in selectors:
            try:
                el = driver.find_element(By.CSS_SELECTOR, css)
                if el.is_displayed():
                    el.click()
                    _sleep(0.5, 1.0)
                    return True
            except Exception:
                pass
        time.sleep(0.2)
    return False


def _is_logged_in(driver) -> bool:
    from selenium.webdriver.common.by import By
    try:
        driver.get(BASE_URL + "/")
        _sleep(2, 3)
        if "/accounts/login" in driver.current_url:
            return False
        # Instagram layout changes often; these checks are intentionally broad.
        candidates = [
            "a[href='/direct/inbox/']",
            "svg[aria-label='Home']",
            "svg[aria-label='New post']",
            "a[href*='/accounts/edit']",
        ]
        for css in candidates:
            if driver.find_elements(By.CSS_SELECTOR, css):
                return True
        return "instagram.com" in driver.current_url and "/accounts/login" not in driver.current_url
    except Exception:
        return False


def _login(driver, parameters: dict, player=None) -> str:
    # Manual browser login: the user signs in themselves. JARVIS never reads,
    # types, or stores the password — only the resulting session is persisted
    # in the (gitignored) browser profile.
    driver.get(BASE_URL + "/")
    _sleep(2, 3)

    if _is_logged_in(driver):
        return "Instagram is already logged in using the saved browser profile."

    driver.get(BASE_URL + "/accounts/login/")
    _sleep(1, 2)
    _log(player, "[IG] Please sign in in the browser window (username + password + 2FA). "
                 "Your password is never read or stored by JARVIS.")

    deadline = time.time() + int(parameters.get("login_timeout", 300))
    while time.time() < deadline:
        try:
            current = driver.current_url
        except Exception:
            break
        if any(s in current for s in ("/challenge", "two_factor", "/checkpoint")):
            _log(player, "[IG] Complete the verification in the browser.")
        elif "instagram.com" in current and "/accounts/login" not in current:
            _sleep(1, 2)
            if _is_logged_in(driver):
                _click_if_present(driver, ["button._a9--._a9_1", "button._a9--._a9_0"], timeout=2)
                return "✅ Instagram connected. Session saved in the browser profile."
        time.sleep(2)

    return (
        "Login wasn't completed in time. Finish signing in in the browser, then say "
        "'instagram status'. Your session is saved once you're logged in."
    )


def _ensure_logged_in(driver, parameters: dict, player=None) -> str | None:
    if _is_logged_in(driver):
        return None
    msg = _login(driver, parameters, player=player)
    if not _is_logged_in(driver):
        return msg
    return None


def _open_url(driver, url: str) -> str:
    if not url.startswith("http"):
        url = BASE_URL + "/" + url.lstrip("/")
    driver.get(url)
    _sleep(2, 4)
    return f"Opened {url}"


def _search(driver, query: str) -> str:
    q = query.strip().replace(" ", "%20")
    url = f"{BASE_URL}/explore/search/keyword/?q={q}"
    driver.get(url)
    _sleep(2, 4)
    return f"Opened Instagram search for: {query}"


def _profile(driver, username: str) -> str:
    username = username.strip().lstrip("@")
    driver.get(f"{BASE_URL}/{username}/")
    _sleep(2, 4)
    return f"Opened Instagram profile @{username}."


def _click_button_by_text(driver, texts: list[str]) -> bool:
    from selenium.webdriver.common.by import By
    text_expr = " or ".join([f"normalize-space()='{t}'" for t in texts])
    xpaths = [
        f"//button[{text_expr}]",
        f"//div[@role='button' and ({text_expr})]",
        f"//*[self::button or @role='button'][contains(translate(normalize-space(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{texts[0].lower()}')]",
    ]
    for xp in xpaths:
        try:
            el = driver.find_element(By.XPATH, xp)
            if el.is_displayed():
                el.click()
                _sleep(1, 2)
                return True
        except Exception:
            pass
    return False


def _follow(driver, username: str, unfollow: bool = False) -> str:
    _profile(driver, username)
    if unfollow:
        if _click_button_by_text(driver, ["Following", "Requested"]):
            _sleep(0.5, 1.2)
            _click_button_by_text(driver, ["Unfollow"])
            return f"Unfollow action attempted for @{username}."
        return f"Could not find following button for @{username}."
    else:
        if _click_button_by_text(driver, ["Follow"]):
            return f"Follow action attempted for @{username}."
        return f"Could not find Follow button for @{username}; maybe already following."


def _like_post(driver, post_url: str) -> str:
    from selenium.webdriver.common.by import By
    _open_url(driver, post_url)
    selectors = [
        "svg[aria-label='Like']",
        "span svg[aria-label='Like']",
    ]
    for css in selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, css)
            el.find_element(By.XPATH, "./ancestor::*[self::button or @role='button'][1]").click()
            _sleep(1, 2)
            return "Post liked."
        except Exception:
            try:
                el = driver.find_element(By.CSS_SELECTOR, css)
                el.click()
                _sleep(1, 2)
                return "Post liked."
            except Exception:
                pass
    return "Could not find Like button; post may already be liked or layout changed."


def _comment_post(driver, post_url: str, text: str) -> str:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    _open_url(driver, post_url)
    _sleep(1, 2)
    try:
        box = driver.find_element(By.CSS_SELECTOR, "textarea[aria-label='Add a comment…'], textarea[placeholder*='comment']")
        box.click()
        _sleep(0.3, 0.8)
        box.send_keys(text)
        _sleep(0.5, 1.0)
        box.send_keys(Keys.ENTER)
        _sleep(1, 2)
        return "Comment posted."
    except Exception:
        return "Could not find comment box; comments may be disabled or layout changed."


def _send_dm(driver, username: str, message: str) -> str:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    username = username.strip().lstrip("@")
    driver.get(f"{BASE_URL}/direct/new/")
    _sleep(3, 5)

    _click_if_present(driver, ["button._a9--._a9_1", "button._a9--._a9_0"], timeout=2)

    try:
        search = _find(driver, By.CSS_SELECTOR, "input[name='queryBox']", timeout=20)
        search.send_keys(username)
        _sleep(2, 3)
        # Select first result matching user.
        candidates = driver.find_elements(By.XPATH, f"//*[contains(text(), '{username}')]")
        if candidates:
            candidates[0].click()
            _sleep(1, 2)
        else:
            return f"Could not find @{username} in DM recipient search."

        if not _click_button_by_text(driver, ["Chat", "Next"]):
            return "Could not open DM chat after selecting recipient."

        _sleep(2, 4)
        boxes = driver.find_elements(By.CSS_SELECTOR, "div[contenteditable='true'][role='textbox']")
        if not boxes:
            boxes = driver.find_elements(By.XPATH, "//*[@contenteditable='true']")
        if not boxes:
            return "Could not find DM message box."
        boxes[-1].click()
        boxes[-1].send_keys(message)
        boxes[-1].send_keys(Keys.ENTER)
        _sleep(1, 2)
        return f"DM sent to @{username}."
    except Exception as e:
        return f"Could not send DM: {e}"


def _post_media(driver, media_path: str, caption: str = "") -> str:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    path = Path(media_path).expanduser().resolve()
    if not path.exists():
        return f"Media file not found: {path}"

    driver.get(BASE_URL + "/")
    _sleep(2, 4)

    # Click Create/New Post.
    clicked = False
    selectors = [
        "svg[aria-label='New post']",
        "svg[aria-label='Create']",
        "a[href='/create/select/']",
    ]
    for css in selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, css)
            try:
                el.find_element(By.XPATH, "./ancestor::*[self::a or self::button or @role='button'][1]").click()
            except Exception:
                el.click()
            clicked = True
            break
        except Exception:
            pass

    if not clicked:
        driver.get(BASE_URL + "/create/select/")

    _sleep(2, 4)

    # Upload file. Instagram uses a hidden input.
    inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
    if not inputs:
        return "Could not find media upload input. Instagram layout may have changed."

    inputs[0].send_keys(str(path))
    _sleep(3, 6)

    # Click Next twice when present.
    for _ in range(2):
        _click_button_by_text(driver, ["Next"])
        _sleep(1.5, 3)

    if caption:
        try:
            boxes = driver.find_elements(By.CSS_SELECTOR, "div[contenteditable='true'][role='textbox']")
            if boxes:
                boxes[-1].click()
                boxes[-1].send_keys(caption)
                _sleep(1, 2)
        except Exception:
            pass

    if _click_button_by_text(driver, ["Share"]):
        _sleep(3, 6)
        return f"Media posted: {path.name}"

    return "Upload prepared but could not find Share button. Please finish manually in the browser."


def _scroll_feed(driver, amount: int = 5) -> str:
    driver.get(BASE_URL + "/")
    _sleep(2, 3)
    amount = max(1, min(int(amount), 20))
    for _ in range(amount):
        driver.execute_script("window.scrollBy(0, arguments[0]);", random.randint(500, 900))
        _sleep(1.5, 3.0)
    return f"Scrolled Instagram feed {amount} times."


def instagram_agent(parameters: dict, player=None, speak=None) -> str:
    action = str(parameters.get("action", "status")).lower().strip()

    if action == "setup":
        return _setup_credentials(parameters)

    if action in ("open", "browser"):
        url = parameters.get("url") or BASE_URL
        if not str(url).startswith("http"):
            url = BASE_URL + "/" + str(url).lstrip("/")
        webbrowser.open(url)
        return f"Opened Instagram in browser: {url}"

    driver = None
    try:
        driver = _make_driver(parameters, player=player)

        if action == "login":
            return _login(driver, parameters, player=player)

        if action == "status":
            return "Instagram logged in." if _is_logged_in(driver) else "Instagram not logged in."

        login_msg = _ensure_logged_in(driver, parameters, player=player)
        if login_msg:
            return login_msg

        if action in ("feed", "home"):
            return _open_url(driver, BASE_URL + "/")

        if action in ("messages", "inbox", "direct"):
            return _open_url(driver, BASE_URL + "/direct/inbox/")

        if action in ("notifications", "activity"):
            return _open_url(driver, BASE_URL + "/accounts/activity/")

        if action == "reels":
            return _open_url(driver, BASE_URL + "/reels/")

        if action == "explore":
            return _open_url(driver, BASE_URL + "/explore/")

        if action == "profile":
            username = parameters.get("username") or _get_credential(parameters, "username")
            if not username:
                return "Provide username for profile action."
            return _profile(driver, username)

        if action == "search":
            query = parameters.get("query", "")
            if not query:
                return "Provide query for search action."
            return _search(driver, query)

        if action == "follow":
            confirm_msg = _require_confirm(parameters, action)
            if confirm_msg:
                return confirm_msg
            username = parameters.get("username", "")
            if not username:
                return "Provide username to follow."
            return _follow(driver, username, unfollow=False)

        if action == "unfollow":
            confirm_msg = _require_confirm(parameters, action)
            if confirm_msg:
                return confirm_msg
            username = parameters.get("username", "")
            if not username:
                return "Provide username to unfollow."
            return _follow(driver, username, unfollow=True)

        if action in ("like", "like_post"):
            confirm_msg = _require_confirm(parameters, action)
            if confirm_msg:
                return confirm_msg
            post_url = parameters.get("url", "")
            if not post_url:
                return "Provide post URL to like."
            return _like_post(driver, post_url)

        if action in ("comment", "comment_post"):
            confirm_msg = _require_confirm(parameters, action)
            if confirm_msg:
                return confirm_msg
            post_url = parameters.get("url", "")
            text = parameters.get("text") or parameters.get("message") or parameters.get("comment", "")
            if not post_url or not text:
                return "Provide url and text/comment to comment on a post."
            return _comment_post(driver, post_url, text)

        if action in ("dm", "send_dm", "message"):
            confirm_msg = _require_confirm(parameters, action)
            if confirm_msg:
                return confirm_msg
            username = parameters.get("username", "")
            message = parameters.get("message") or parameters.get("text", "")
            if not username or not message:
                return "Provide username and message for DM."
            return _send_dm(driver, username, message)

        if action in ("post", "upload", "post_media", "post_photo", "post_video"):
            confirm_msg = _require_confirm(parameters, action)
            if confirm_msg:
                return confirm_msg
            media_path = parameters.get("media_path") or parameters.get("image_path") or parameters.get("video_path") or parameters.get("path")
            caption = parameters.get("caption", "")
            if not media_path:
                return "Provide media_path/image_path/video_path to post."
            return _post_media(driver, media_path, caption)

        if action in ("scroll", "scroll_feed"):
            amount = int(parameters.get("amount", 5))
            return _scroll_feed(driver, amount)

        if action == "logout":
            confirm_msg = _require_confirm(parameters, action)
            if confirm_msg:
                return confirm_msg
            driver.get(BASE_URL + "/accounts/logout/")
            _sleep(2, 4)
            return "Instagram logout opened. Confirm any browser prompt if shown."

        return f"Unknown Instagram action: {action}"

    except Exception as e:
        traceback.print_exc()
        return f"Instagram agent failed: {e}"
