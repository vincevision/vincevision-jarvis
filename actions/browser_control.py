from __future__ import annotations

import core.env_setup  # noqa: F401

import asyncio
import os
import platform
import shutil
import subprocess
import threading
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

_OS = platform.system()


# ══════════════════════════════════════════════════════════════════════════
#  USER / HOME HELPERS
# ══════════════════════════════════════════════════════════════════════════

def _get_real_user() -> tuple[str, int]:
    for var in ["SUDO_USER", "JARVIS_REAL_USER"]:
        user = os.environ.get(var, "").strip()
        if user and user != "root":
            try:
                import pwd
                info = pwd.getpwnam(user)
                return user, info.pw_uid
            except Exception:
                pass
    try:
        import pwd
        for entry in pwd.getpwall():
            if entry.pw_uid >= 1000:
                return entry.pw_name, entry.pw_uid
    except Exception:
        pass
    return os.environ.get("USER") or "user", 1000


def _get_real_home() -> Path:
    user, _ = _get_real_user()
    home = Path(f"/home/{user}")
    if home.exists():
        return home
    if user == "root":
        h = Path("/root")
        if h.exists():
            return h
    return Path.home()


def _normalize_url(url: str) -> str:
    url = url.strip()
    if not url:
        return "about:blank"
    if "://" in url:
        return url
    if "." not in url:
        url += ".com"
    return "https://" + url


def _fix_dir_ownership(path: Path, user: str, uid: int) -> None:
    """Create dir owned by real user; fix if root previously created it."""
    if _running_as_root() and user:
        # Always use sudo -u so the new dir is owned by the real user
        try:
            subprocess.run(
                ["sudo", "-u", user, "mkdir", "-p", str(path)],
                timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            path.mkdir(parents=True, exist_ok=True)
        # Fix ownership regardless (catches dirs root made previously)
        try:
            if path.exists() and path.stat().st_uid == 0:
                print(f"[Browser] 🔧 chown {path.name} → {user}")
                subprocess.run(
                    ["chown", "-R", f"{uid}:{uid}", str(path)],
                    timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
        except Exception as e:
            print(f"[Browser] ⚠️  chown failed: {e}")
    else:
        path.mkdir(parents=True, exist_ok=True)


def _jarvis_profile_dir(browser: str, user: str = "", uid: int = 0) -> str:
    """
    Return the browser profile path. Creates BOTH the main profile and the
    _visible variant upfront, both owned by the real user — never root.
    This prevents the SingletonLock Permission Denied error.
    """
    base    = _get_real_home() / ".config" / "jarvis" / f"{browser}_profile"
    visible = _get_real_home() / ".config" / "jarvis" / f"{browser}_profile_visible"
    _fix_dir_ownership(base,    user, uid)
    _fix_dir_ownership(visible, user, uid)
    return str(base)


# ══════════════════════════════════════════════════════════════════════════
#  RUNNING AS ROOT?
#  When JARVIS runs as root the browser MUST be launched as the real user
#  (the desktop user).  Root cannot connect to that user's D-Bus/X11 session, which
#  causes the GTK segfault we see.  We detect this and wrap the Playwright
#  launch with `sudo -u <user> -E` so the browser inherits the right session.
# ══════════════════════════════════════════════════════════════════════════

def _running_as_root() -> bool:
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False


def _build_env_for_user(user: str, uid: int) -> dict:
    """Build a clean environment for the real user's session."""
    env = dict(os.environ)

    real_home = str(_get_real_home())
    env["HOME"]    = real_home
    env["USER"]    = user
    env["LOGNAME"] = user
    env["DISPLAY"] = env.get("DISPLAY", ":0")

    # XDG runtime dir (owns the D-Bus socket)
    xdg = f"/run/user/{uid}"
    if Path(xdg).exists():
        env["XDG_RUNTIME_DIR"] = xdg

    # D-Bus — must be the USER's socket, not root's
    dbus_sock = f"/run/user/{uid}/bus"
    if Path(dbus_sock).exists():
        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={dbus_sock}"
        print(f"[Browser] 🔌 D-Bus: {dbus_sock}")
    else:
        # Try to find it via loginctl / systemctl
        try:
            out = subprocess.check_output(
                ["sudo", "-u", user, "systemctl", "--user",
                 "show-environment", "--no-pager"],
                timeout=4, text=True, stderr=subprocess.DEVNULL
            )
            for line in out.splitlines():
                if line.startswith("DBUS_SESSION_BUS_ADDRESS="):
                    env["DBUS_SESSION_BUS_ADDRESS"] = line.split("=", 1)[1]
                    break
        except Exception:
            pass

        if "DBUS_SESSION_BUS_ADDRESS" not in env:
            env["DBUS_SESSION_BUS_ADDRESS"] = "disabled:"
            print("[Browser] ⚠️  D-Bus socket not found — visible mode may fail")

    # Xauthority
    for xauth_path in [
        Path(real_home) / ".Xauthority",
        Path(f"/run/user/{uid}/.mutter-Xwaylandauth"),
    ]:
        if xauth_path.exists() and xauth_path.stat().st_size > 0:
            env["XAUTHORITY"] = str(xauth_path)
            break

    # Strip sudo variables
    for v in ["SUDO_USER", "SUDO_HOME", "SUDO_UID", "SUDO_GID"]:
        env.pop(v, None)

    return env


# ══════════════════════════════════════════════════════════════════════════
#  LAUNCH ARGS  (de-duped — Playwright already adds most common flags)
# ══════════════════════════════════════════════════════════════════════════

def _get_args(headless: bool) -> list[str]:
    args = [
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-sync",
        "--disable-blink-features=AutomationControlled",
        "--disable-crash-reporter",
        "--disable-breakpad",
        "--noerrdialogs",
        "--disable-component-update",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--enable-unsafe-swiftshader",
        "--use-gl=swiftshader",
        "--disable-dev-shm-usage",
        "--password-store=basic",
        "--use-mock-keychain",
        "--disable-features=MediaRouter,DialMediaRouteProvider,TranslateUI,"
        "ThirdPartyStoragePartitioning,HttpsUpgrades",
    ]
    if not headless:
        args.append("--start-maximized")
    return args


# ══════════════════════════════════════════════════════════════════════════
#  BROWSER RESOLUTION
# ══════════════════════════════════════════════════════════════════════════

_SPECS = {
    "Linux": {
        "chromium": {"engine": "chromium", "bins": ["chromium-browser", "chromium"]},
        "chrome":   {"engine": "chromium", "bins": ["google-chrome", "google-chrome-stable"]},
        "brave":    {"engine": "chromium", "bins": ["brave-browser", "brave"]},
        "firefox":  {"engine": "firefox",  "bins": ["firefox", "firefox-bin"]},
        "edge":     {"engine": "chromium", "bins": ["microsoft-edge", "microsoft-edge-stable"]},
    }
}
_FALLBACK = ["brave", "chromium", "chrome", "firefox", "edge"]


def _resolve(name: str):
    spec = _SPECS.get(_OS, {}).get(name.lower())
    if not spec:
        return None
    exe = next((shutil.which(b) for b in spec["bins"] if shutil.which(b)), None)
    return {"engine": spec["engine"], "exe": exe}


def _resolve_with_fallback(name: str):
    r = _resolve(name)
    if r and r["exe"]:
        return name, r
    print(f"[Browser] ⚠️  '{name}' not found")
    for fb in _FALLBACK:
        if fb == name:
            continue
        r = _resolve(fb)
        if r and r["exe"]:
            print(f"[Browser] ✅ Fallback: {fb}")
            return fb, r
    print("[Browser] 📦 Using Playwright's bundled Chromium")
    return "chromium", {"engine": "chromium", "exe": None}


# ══════════════════════════════════════════════════════════════════════════
#  BROWSER SESSION
# ══════════════════════════════════════════════════════════════════════════

class _BrowserSession:
    def __init__(self, browser_name: str):
        self.browser_name = browser_name
        self._loop    = None
        self._thread  = None
        self._ready   = threading.Event()
        self._pw      = None
        self._context = None
        self._page    = None
        self._headless = False

    # ── Thread / loop ──────────────────────────────────────────────────────

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True,
            name=f"browser-{self.browser_name}"
        )
        self._thread.start()
        if not self._ready.wait(timeout=30):
            raise RuntimeError(f"[Browser] ❌ '{self.browser_name}' init timed out")

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_init())
        except Exception as e:
            print(f"[Browser] ❌ Init error: {e}")
        finally:
            self._ready.set()
        try:
            self._loop.run_forever()
        except Exception as e:
            print(f"[Browser] ❌ Loop error: {e}")

    async def _async_init(self):
        self._pw = await async_playwright().start()

    def run(self, coro, timeout: int = 60):
        if not self._loop:
            raise RuntimeError("Browser not started")
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    # ── Launch ─────────────────────────────────────────────────────────────

    async def _launch(self, headless: bool = False):
        if self._context is not None:
            return

        actual_name, spec = _resolve_with_fallback(self.browser_name)
        if actual_name != self.browser_name:
            self.browser_name = actual_name

        engine_obj = getattr(self._pw, spec["engine"])
        user, uid  = _get_real_user()
        profile    = _jarvis_profile_dir(self.browser_name, user, uid)
        env        = _build_env_for_user(user, uid)

        print(f"[Browser] 👤 User   : {user} (uid={uid})")
        print(f"[Browser] 🏠 Home   : {_get_real_home()}")
        print(f"[Browser] 📁 Profile: {profile}")
        print(f"[Browser] 🔌 D-Bus  : {env.get('DBUS_SESSION_BUS_ADDRESS', '?')}")

        base_kwargs = {
            "slow_mo":     0,
            "viewport":    None,
            "no_viewport": True,
            "args":        _get_args(headless),
            "env":         env,
        }
        if spec["exe"]:
            base_kwargs["executable_path"] = spec["exe"]

        # ── Strategy: if running as root, try sudo -u <user> wrapper first ──
        #    Root cannot own the X11/D-Bus session → browser segfaults.
        #    We launch the browser subprocess as the real user instead.
        attempts: list[tuple[bool, bool]] = []  # (headless, use_su)

        if _running_as_root():
            print(f"[Browser] 🔑 Running as root — will try su to '{user}' for visible mode")
            if not headless:
                attempts = [(False, True), (False, False), (True, False)]
            else:
                attempts = [(True, False)]
        else:
            attempts = [(headless, False)] if headless else [(False, False), (True, False)]

        for attempt_headless, use_su in attempts:
            mode = ("headless" if attempt_headless else "visible") + (" [su]" if use_su else "")
            print(f"[Browser] 🚀 Launching {self.browser_name} ({mode})")

            kwargs = {**base_kwargs, "headless": attempt_headless,
                      "args": _get_args(attempt_headless)}

            # When running as root, patch the executable path to go through
            # `sudo -u <user> -E` so the process owns the X11/D-Bus session.
            if use_su and spec["exe"] and _running_as_root():
                # Playwright's launch_persistent_context doesn't support
                # wrapping the binary natively, so we pre-launch the browser
                # ourselves via subprocess and then connect via CDP.
                result = await self._launch_via_su(
                    user, spec["exe"], profile, env, attempt_headless
                )
                if result:
                    return
                print(f"[Browser] ⚠️  su launch failed, trying next strategy")
                continue

            try:
                self._context = await engine_obj.launch_persistent_context(
                    profile, **kwargs
                )
                await asyncio.sleep(0.8)
                pages = self._context.pages
                self._page = pages[0] if pages else await self._context.new_page()
                print(f"[Browser] ✅ Ready ({mode})")
                return
            except Exception as e:
                self._context = None
                self._page    = None
                print(f"[Browser] ❌ Failed ({mode}): {str(e)[:200]}")

        raise RuntimeError(
            f"All launch strategies failed for '{self.browser_name}'.\n\n"
            "💡 Try one of these:\n"
            "   1. Run JARVIS as your desktop user instead of root:\n"
            f"      sudo -u {user} python3 main.py\n"
            "   2. Or grant root access to your X11 session:\n"
            "      xhost +local:root\n"
            f"      export XAUTHORITY=/home/{user}/.Xauthority\n"
            f"      export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus\n"
            "   3. Or always use headless:\n"
            "      browser_control({'action':'go_to','url':'...','headless':True})"
        )

    async def _launch_via_su(
        self, user: str, exe: str, profile: str, env: dict, headless: bool
    ) -> bool:
        """
        Launch the browser as the real user via sudo, connect via CDP.
        Uses a separate profile dir to avoid SingletonLock conflicts with
        any headless instance that may already be running.
        """
        port = 19222

        # Use a dedicated visible-mode profile (created + chowned in _jarvis_profile_dir)
        vis_profile = profile.rstrip("/") + "_visible"

        args = _get_args(headless) + [
            f"--remote-debugging-port={port}",
            f"--user-data-dir={vis_profile}",
            "--remote-allow-origins=*",
        ]
        if headless:
            args.append("--headless=new")

        # Build the command: sudo -u <user> env VAR=val ... brave-browser ...
        env_pairs = []
        for k in ["DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS",
                  "XDG_RUNTIME_DIR", "HOME", "USER"]:
            if k in env:
                env_pairs.append(f"{k}={env[k]}")

        cmd = ["sudo", "-u", user, "env"] + env_pairs + [exe] + args

        print(f"[Browser] 🔧 su cmd: sudo -u {user} env ... {exe} ...")
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as e:
            print(f"[Browser] ❌ su subprocess failed: {e}")
            return False

        # Wait for the debugging port to become available
        for i in range(20):
            await asyncio.sleep(0.5)
            try:
                import urllib.request
                urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1)
                break
            except Exception:
                # Check if process already died
                if proc.returncode is not None:
                    stderr_data = await proc.stderr.read()
                    print(f"[Browser] ❌ su browser died early: {stderr_data.decode()[:300]}")
                    return False
        else:
            proc.kill()
            print("[Browser] ❌ CDP port never opened")
            return False

        # Connect Playwright to the running browser
        try:
            self._context = await self._pw.chromium.connect_over_cdp(
                f"http://127.0.0.1:{port}"
            )
            pages = self._context.pages if hasattr(self._context, "pages") else []
            # connect_over_cdp returns a Browser not BrowserContext — get default ctx
            if hasattr(self._context, "contexts"):
                ctxs = self._context.contexts
                ctx  = ctxs[0] if ctxs else await self._context.new_context()
                pages = ctx.pages
                self._page = pages[0] if pages else await ctx.new_page()
                self._context = ctx
            else:
                self._page = pages[0] if pages else await self._context.new_page()
            print(f"[Browser] ✅ Connected via CDP to su-launched browser")
            return True
        except Exception as e:
            print(f"[Browser] ❌ CDP connect failed: {e}")
            try:
                proc.kill()
            except Exception:
                pass
            self._context = None
            self._page    = None
            return False

    async def _get_page(self):
        await self._launch(self._headless)
        if self._page is None or self._page.is_closed():
            pages = self._context.pages
            self._page = pages[-1] if pages else await self._context.new_page()
        return self._page

    # ── Actions ────────────────────────────────────────────────────────────

    async def go_to(self, url: str) -> str:
        url  = _normalize_url(url)
        page = await self._get_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except PlaywrightTimeout:
            pass
        return f"Opened: {page.url}"

    async def search(self, query: str, engine: str = "google") -> str:
        urls = {
            "google":     f"https://www.google.com/search?q={query}",
            "bing":       f"https://www.bing.com/search?q={query}",
            "duckduckgo": f"https://duckduckgo.com/?q={query}",
        }
        return await self.go_to(urls.get(engine.lower(), urls["google"]))

    async def new_tab(self, url: str = "") -> str:
        await self._launch(self._headless)
        self._page = await self._context.new_page()
        if url:
            return await self.go_to(url)
        return "New tab opened"

    async def close_tab(self) -> str:
        page = await self._get_page()
        await page.close()
        pages = self._context.pages
        self._page = pages[-1] if pages else await self._context.new_page()
        return "Tab closed"

    async def get_url(self) -> str:
        return (await self._get_page()).url

    async def get_text(self) -> str:
        try:
            return (await (await self._get_page()).inner_text("body"))[:2000]
        except Exception as e:
            return f"Could not extract text: {e}"

    async def click(self, selector: str = "", text: str = "") -> str:
        page = await self._get_page()
        try:
            if text:
                el = page.get_by_text(text, exact=False)
                if await el.count() > 0:
                    await el.first.click(timeout=8000)
                    return f"Clicked: '{text}'"
            if selector:
                await page.click(selector, timeout=8000)
                return f"Clicked: {selector}"
            return "No selector or text provided"
        except Exception as e:
            return f"Click failed: {e}"

    async def smart_click(self, description: str) -> str:
        page = await self._get_page()
        try:
            for role in ["button", "link", "menuitem"]:
                el = page.get_by_role(role, name=description)
                if await el.count() > 0:
                    await el.first.click(timeout=5000)
                    return f"Clicked {role}: '{description}'"
            el = page.get_by_text(description, exact=False)
            if await el.count() > 0:
                await el.first.click(timeout=5000)
                return f"Clicked: '{description}'"
            return f"Element not found: '{description}'"
        except Exception as e:
            return f"Smart click failed: {e}"

    async def type_text(self, selector="", text="",
                        description="", clear_first=True) -> str:
        page = await self._get_page()
        try:
            if description:
                el = page.get_by_placeholder(description)
                if await el.count() == 0:
                    el = page.get_by_label(description)
                if await el.count() > 0:
                    if clear_first:
                        await el.first.clear()
                    await el.first.type(text, delay=30)
                    return f"Typed into '{description}'"
            if selector:
                if clear_first:
                    await page.fill(selector, "")
                await page.type(selector, text, delay=30)
                return f"Typed into {selector}"
            if clear_first:
                await page.keyboard.press("Control+a")
            await page.keyboard.type(text, delay=30)
            return f"Typed: '{text}'"
        except Exception as e:
            return f"Type failed: {e}"

    async def press(self, key: str) -> str:
        await (await self._get_page()).keyboard.press(key)
        return f"Pressed: {key}"

    async def scroll(self, direction: str = "down", amount: int = 500) -> str:
        page = await self._get_page()
        await page.mouse.wheel(0, amount if direction == "down" else -amount)
        return f"Scrolled {direction} {amount}px"

    async def screenshot(self, path: str = "") -> str:
        page = await self._get_page()
        if not path:
            path = str(_get_real_home() / "Desktop" / "jarvis_screenshot.png")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=path, full_page=False)
        return f"Screenshot: {path}"

    async def back(self) -> str:
        page = await self._get_page()
        await page.go_back()
        return f"Back to: {page.url}"

    async def forward(self) -> str:
        page = await self._get_page()
        await page.go_forward()
        return f"Forward to: {page.url}"

    async def reload(self) -> str:
        page = await self._get_page()
        await page.reload()
        return f"Reloaded: {page.url}"

    async def fill_form(self, fields: dict) -> str:
        page  = await self._get_page()
        count = 0
        for sel, val in fields.items():
            try:
                await page.fill(sel, val)
                count += 1
            except Exception as e:
                print(f"[Browser] fill {sel}: {e}")
        return f"Filled {count} field(s)"

    async def upload(self, selector="input[type='file']", paths=None) -> str:
        """Attach local file(s) to a file input (Playwright set_input_files)."""
        page = await self._get_page()
        if isinstance(paths, str):
            paths = [p.strip() for p in paths.split(",") if p.strip()]
        files = [str(Path(p).expanduser().resolve()) for p in (paths or [])]
        if not files:
            return "No file path given"
        missing = [f for f in files if not Path(f).exists()]
        if missing:
            return f"File not found: {missing[0]}"
        try:
            await page.set_input_files(selector, files if len(files) > 1 else files[0])
            return f"Attached {len(files)} file(s)"
        except Exception as e:
            return f"Upload failed: {e}"

    async def close(self) -> str:
        if self._context:
            await self._context.close()
            self._context = None
            self._page    = None
        return "Browser closed"


# ══════════════════════════════════════════════════════════════════════════
#  SESSION REGISTRY
# ══════════════════════════════════════════════════════════════════════════

class _SessionRegistry:
    def __init__(self):
        self._sessions: dict[str, _BrowserSession] = {}
        self._lock = threading.Lock()

    def get(self, browser_name: str = "brave",
            headless: bool = False) -> _BrowserSession:
        with self._lock:
            if browser_name not in self._sessions:
                sess = _BrowserSession(browser_name)
                sess._headless = headless
                sess.start()
                self._sessions[browser_name] = sess
            else:
                self._sessions[browser_name]._headless = headless
            return self._sessions[browser_name]

    def close_all(self) -> str:
        results = []
        with self._lock:
            for name, sess in list(self._sessions.items()):
                try:
                    sess.run(sess.close(), timeout=10)
                    results.append(f"{name} closed")
                except Exception as e:
                    results.append(f"{name}: {e}")
            self._sessions.clear()
        return ", ".join(results) or "No browsers open"

    def list_browsers(self) -> list[str]:
        with self._lock:
            return list(self._sessions.keys())


_registry = _SessionRegistry()


# ══════════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════════════

def browser_control(parameters: dict = None, player=None, **kwargs) -> str:
    params   = parameters or {}
    action   = params.get("action", "go_to").lower().strip()
    browser  = params.get("browser", "brave").lower().strip()
    headless = params.get("headless", False)

    def log(msg: str):
        if player:
            player.write_log(f"[browser] {msg[:120]}")
        print(f"[Browser] {msg}")

    try:
        if action == "list_browsers":
            result = str(_registry.list_browsers())
        elif action == "close_all":
            result = _registry.close_all()
        else:
            sess = _registry.get(browser, headless=headless)

            if action == "go_to":
                result = sess.run(sess.go_to(params.get("url", "")))
            elif action == "search":
                result = sess.run(sess.search(
                    params.get("query", ""), params.get("engine", "google")))
            elif action == "new_tab":
                result = sess.run(sess.new_tab(params.get("url", "")))
            elif action == "close_tab":
                result = sess.run(sess.close_tab())
            elif action == "close":
                result = sess.run(sess.close())
                with _registry._lock:
                    _registry._sessions.pop(browser, None)
            elif action == "get_url":
                result = sess.run(sess.get_url())
            elif action == "get_text":
                result = sess.run(sess.get_text())
            elif action in ("click", "smart_click"):
                if action == "smart_click" or params.get("description"):
                    result = sess.run(sess.smart_click(
                        params.get("description", params.get("text", ""))))
                else:
                    result = sess.run(sess.click(
                        params.get("selector", ""), params.get("text", "")))
            elif action in ("type", "smart_type"):
                result = sess.run(sess.type_text(
                    selector=params.get("selector", ""),
                    text=params.get("text", ""),
                    description=params.get("description", ""),
                    clear_first=params.get("clear_first", True),
                ))
            elif action == "press":
                result = sess.run(sess.press(params.get("key", "Enter")))
            elif action == "scroll":
                result = sess.run(sess.scroll(
                    params.get("direction", "down"),
                    int(params.get("amount", 500))))
            elif action == "screenshot":
                result = sess.run(sess.screenshot(params.get("path", "")))
            elif action == "back":
                result = sess.run(sess.back())
            elif action == "forward":
                result = sess.run(sess.forward())
            elif action == "reload":
                result = sess.run(sess.reload())
            elif action == "fill_form":
                result = sess.run(sess.fill_form(params.get("fields", {})))
            elif action in ("upload", "upload_file", "attach"):
                result = sess.run(sess.upload(
                    params.get("selector", "input[type='file']"),
                    params.get("paths") or params.get("path") or params.get("media")))
            elif action == "switch":
                browser = params.get("browser", browser)
                sess    = _registry.get(browser, headless=headless)
                result  = f"Switched to {browser}"
            else:
                result = (
                    f"Unknown action: '{action}'. Valid: go_to, search, click, "
                    "smart_click, type, smart_type, press, scroll, screenshot, "
                    "new_tab, close_tab, back, forward, reload, fill_form, "
                    "get_url, get_text, close, close_all, switch, list_browsers"
                )

    except Exception as e:
        result = f"Browser error: {e}"
        import traceback
        traceback.print_exc()

    log(result)
    return result