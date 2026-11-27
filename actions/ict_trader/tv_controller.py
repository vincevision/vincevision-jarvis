"""
TradingView Browser Controller
GNOME Wayland + X11 Compatible

Confirmed working on this system:
  - GNOME Wayland (XDG_SESSION_TYPE=wayland)
  - XWayland available at DISPLAY=:0
  - scrot confirmed working via XWayland
  - gdbus AccessDenied (blocked by GNOME security)

Screenshot priority:
  1. scrot via XWayland     ✅ CONFIRMED
  2. mss via XWayland       ✅ installed
  3. xwd via XWayland       ✅ installed
  4. spectacle              ✅ installed
  5. flameshot              ✅ installed
  6. PIL via XWayland       ✅ installed
"""

import os
import sys
import json
import subprocess
import time
import traceback
import pyautogui
from pathlib import Path

pyautogui.FAILSAFE = False
pyautogui.PAUSE    = 0.12

TV_TIMEFRAMES = {
    "1m":     "1",    "3m":    "3",    "5m":    "5",
    "15m":    "15",   "30m":   "30",
    "1h":     "60",   "2h":    "120",  "4h":    "240",
    "1d":     "D",    "1w":    "W",    "1M":    "M",
    "1min":   "1",    "5min":  "5",    "15min": "15",
    "30min":  "30",   "1hr":   "60",   "4hr":   "240",
    "daily":  "D",    "weekly":"W",    "monthly":"M",
    "D":      "D",    "W":     "W",    "M":     "M",
}


def _xwayland_env() -> dict:
    """
    Build environment dict that forces XWayland (X11) mode.
    scrot, mss, xwd all need DISPLAY=:0 and no WAYLAND_DISPLAY.
    """
    env = dict(os.environ)
    env["DISPLAY"]          = ":0"
    env["WAYLAND_DISPLAY"]  = ""      # Empty string forces X11 mode
    env["GDK_BACKEND"]      = "x11"
    env["QT_QPA_PLATFORM"]  = "xcb"
    return env


class TVController:
    """
    Controls TradingView in the browser.
    Handles opening, symbol/timeframe changes, screenshots, and focus.
    Optimised for GNOME Wayland with XWayland fallback.
    """

    def __init__(self, browser: str = "firefox", player=None, speak=None):
        self.browser           = browser
        self.player            = player
        self.speak             = speak
        self._tv_url           = "https://www.tradingview.com/chart"
        self._ready            = False
        self._is_wayland       = self._detect_wayland()
        self._wayland_display  = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
        self._display          = os.environ.get("DISPLAY", ":0")
        self._best_ss_method   = None   # cached after first successful screenshot

        print(
            f"[TV-CTRL] Session: GNOME Wayland | "
            f"WAYLAND={self._wayland_display} | "
            f"DISPLAY={self._display}"
        )

    # ── Logging ──────────────────────────────────────────────────────────
    def log(self, msg: str):
        print(f"[TV-CTRL] {msg}")
        if self.player:
            try:
                self.player.write_log(f"[TV] {msg}")
            except Exception:
                pass

    # ── Display Detection ────────────────────────────────────────────────
    def _detect_wayland(self) -> bool:
        return (
            bool(os.environ.get("WAYLAND_DISPLAY")) or
            os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
        )

    # ════════════════════════════════════════════════════════════════════
    #  SCREENSHOT — MAIN ENTRY POINT
    # ════════════════════════════════════════════════════════════════════
    def take_screenshot(self, save_path: str = "") -> str:
        """
        Take a full-screen screenshot.

        Uses scrot via XWayland as primary method (confirmed working).
        Falls back through mss → xwd → spectacle → flameshot → PIL.

        Args:
            save_path: Optional full path to save PNG. Auto-generated if empty.

        Returns:
            Path to saved PNG, or empty string on failure.
        """
        if not save_path:
            save_dir = Path.home() / ".jarvis" / "ict_trader" / "screenshots"
            save_dir.mkdir(parents=True, exist_ok=True)
            save_path = str(save_dir / f"chart_{int(time.time())}.png")

        # Focus browser window before capturing
        self._focus_tv_window()
        time.sleep(1.0)

        # Use cached method if available
        if self._best_ss_method:
            try:
                result = self._best_ss_method(save_path)
                p = Path(result) if result else None
                if p and p.exists() and p.stat().st_size > 3000:
                    self.log(
                        f"✅ [{self._best_ss_method.__name__}] "
                        f"{p.stat().st_size:,} bytes"
                    )
                    return result
                else:
                    # Cached method stopped working — reset and retry all
                    self.log("Cached method failed — retrying all methods")
                    self._best_ss_method = None
            except Exception as ex:
                self.log(f"Cached method error: {ex} — resetting")
                self._best_ss_method = None

        # Method priority order — scrot first (confirmed working)
        methods = [
            self._ss_scrot_xwayland,    # ✅ CONFIRMED WORKING
            self._ss_mss_xwayland,      # ✅ mss installed
            self._ss_xwd_xwayland,      # ✅ xwd installed
            self._ss_spectacle,         # ✅ spectacle installed
            self._ss_flameshot,         # ✅ flameshot installed
            self._ss_pil_xwayland,      # ✅ PIL installed
            self._ss_scrot_direct,      # bare scrot fallback
        ]

        for method in methods:
            try:
                result = method(save_path)
                if result:
                    p = Path(result)
                    if p.exists() and p.stat().st_size > 3000:
                        self.log(
                            f"✅ [{method.__name__}] "
                            f"{p.stat().st_size:,} bytes"
                        )
                        # Cache this working method for next time
                        self._best_ss_method = method
                        return result
                    elif p.exists():
                        self.log(
                            f"⚠️ [{method.__name__}] file too small: "
                            f"{p.stat().st_size} bytes — skipping"
                        )
            except Exception as ex:
                self.log(f"❌ [{method.__name__}]: {str(ex)[:120]}")
                continue

        self.log("❌ All screenshot methods failed")
        return ""

    # ════════════════════════════════════════════════════════════════════
    #  SCREENSHOT METHOD 1 — scrot via XWayland ✅ CONFIRMED WORKING
    # ════════════════════════════════════════════════════════════════════
    def _ss_scrot_xwayland(self, path: str) -> str:
        """
        scrot screenshot via XWayland.
        Confirmed working: DISPLAY=:0 WAYLAND_DISPLAY="" scrot /tmp/test.png

        scrot is an X11 screenshot tool. Setting DISPLAY=:0 routes it
        through XWayland which captures the full compositor output.
        """
        env = _xwayland_env()

        # Attempt 1: scrot with --silent flag (scrot >= 1.0)
        r = subprocess.run(
            ["scrot", "--silent", path],
            capture_output=True,
            timeout=12,
            env=env,
        )
        if r.returncode == 0 and Path(path).exists():
            if Path(path).stat().st_size > 100:
                return path

        # Attempt 2: scrot without --silent (older versions)
        r = subprocess.run(
            ["scrot", path],
            capture_output=True,
            timeout=12,
            env=env,
        )
        if r.returncode == 0 and Path(path).exists():
            if Path(path).stat().st_size > 100:
                return path

        # Attempt 3: scrot with delay (sometimes needed for window focus)
        r = subprocess.run(
            ["scrot", "--delay", "1", path],
            capture_output=True,
            timeout=15,
            env=env,
        )
        if r.returncode == 0 and Path(path).exists():
            return path

        stderr = r.stderr.decode("utf-8", errors="ignore")
        if stderr:
            self.log(f"scrot stderr: {stderr[:150]}")
        return ""

    # ════════════════════════════════════════════════════════════════════
    #  SCREENSHOT METHOD 2 — mss via XWayland
    # ════════════════════════════════════════════════════════════════════
    def _ss_mss_xwayland(self, path: str) -> str:
        """
        Python mss library via XWayland.
        mss is installed (confirmed by diagnostic).
        Runs in subprocess with XWayland environment.
        """
        abs_path = str(Path(path).resolve())

        # Run as subprocess to isolate environment correctly
        script = (
            "import os\n"
            "os.environ['DISPLAY'] = ':0'\n"
            "os.environ['WAYLAND_DISPLAY'] = ''\n"
            "import mss, mss.tools\n"
            "with mss.mss() as sct:\n"
            "    mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]\n"
            "    img = sct.grab(mon)\n"
            f"    mss.tools.to_png(img.rgb, img.size, output=r'{abs_path}')\n"
            "    print(f'ok:{{img.size}}')\n"
        )

        env = _xwayland_env()
        r   = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )

        stdout = r.stdout.strip()
        stderr = r.stderr.strip()

        if "ok:" in stdout and Path(abs_path).exists():
            if Path(abs_path).stat().st_size > 1000:
                return abs_path

        if stderr:
            self.log(f"mss stderr: {stderr[:100]}")

        # Attempt 2: Direct in-process import with env manipulation
        try:
            saved_display  = os.environ.get("DISPLAY", "")
            saved_wayland  = os.environ.get("WAYLAND_DISPLAY", "")

            os.environ["DISPLAY"]         = ":0"
            os.environ["WAYLAND_DISPLAY"] = ""

            try:
                import mss
                import mss.tools
                with mss.mss() as sct:
                    mon = (
                        sct.monitors[1]
                        if len(sct.monitors) > 1
                        else sct.monitors[0]
                    )
                    img = sct.grab(mon)
                    mss.tools.to_png(img.rgb, img.size, output=abs_path)
                if (Path(abs_path).exists() and
                        Path(abs_path).stat().st_size > 1000):
                    return abs_path
            finally:
                # Restore environment
                os.environ["DISPLAY"] = saved_display
                if saved_wayland:
                    os.environ["WAYLAND_DISPLAY"] = saved_wayland
                else:
                    os.environ.pop("WAYLAND_DISPLAY", None)

        except Exception as e:
            self.log(f"mss direct failed: {e}")

        return ""

    # ════════════════════════════════════════════════════════════════════
    #  SCREENSHOT METHOD 3 — xwd via XWayland
    # ════════════════════════════════════════════════════════════════════
    def _ss_xwd_xwayland(self, path: str) -> str:
        """
        xwd (X Window Dump) via XWayland + PIL conversion.
        xwd is installed (confirmed by diagnostic).
        PIL is installed (confirmed by diagnostic).
        No ImageMagick 'convert' needed — uses PIL directly.
        """
        env = _xwayland_env()
        tmp = path.replace(".png", f"_xwd_{int(time.time())}.xwd")

        # Step 1: Capture root window with xwd
        r1 = subprocess.run(
            ["xwd", "-root", "-silent", "-out", tmp],
            capture_output=True,
            timeout=12,
            env=env,
        )

        if r1.returncode != 0:
            stderr = r1.stderr.decode("utf-8", errors="ignore")
            self.log(f"xwd failed: {stderr[:100]}")
            return ""

        if not Path(tmp).exists() or Path(tmp).stat().st_size < 100:
            self.log("xwd produced empty file")
            return ""

        # Step 2: Convert xwd → PNG using PIL
        try:
            from PIL import Image
            img = Image.open(tmp)
            img.save(path, "PNG")
            Path(tmp).unlink(missing_ok=True)
            if Path(path).exists() and Path(path).stat().st_size > 100:
                return path
        except Exception as e:
            self.log(f"xwd PIL convert failed: {e}")
            try:
                Path(tmp).unlink(missing_ok=True)
            except Exception:
                pass

        return ""

    # ════════════════════════════════════════════════════════════════════
    #  SCREENSHOT METHOD 4 — spectacle
    # ════════════════════════════════════════════════════════════════════
    def _ss_spectacle(self, path: str) -> str:
        """
        KDE Spectacle screenshot tool.
        Installed (confirmed by diagnostic).
        """
        env = dict(os.environ)

        # Try modern spectacle syntax
        r = subprocess.run(
            [
                "spectacle",
                "--background",
                "--nonotify",
                "--fullscreen",
                "--output", path,
            ],
            capture_output=True,
            timeout=12,
            env=env,
        )
        if r.returncode == 0 and Path(path).exists():
            if Path(path).stat().st_size > 100:
                return path

        # Try older spectacle syntax
        r = subprocess.run(
            ["spectacle", "-b", "-n", "-f", "-o", path],
            capture_output=True,
            timeout=12,
            env=env,
        )
        if r.returncode == 0 and Path(path).exists():
            if Path(path).stat().st_size > 100:
                return path

        # Try with XWayland env
        env_x = _xwayland_env()
        r = subprocess.run(
            ["spectacle", "-b", "-n", "-f", "-o", path],
            capture_output=True,
            timeout=12,
            env=env_x,
        )
        return path if (
            r.returncode == 0 and
            Path(path).exists() and
            Path(path).stat().st_size > 100
        ) else ""

    # ════════════════════════════════════════════════════════════════════
    #  SCREENSHOT METHOD 5 — flameshot
    # ════════════════════════════════════════════════════════════════════
    def _ss_flameshot(self, path: str) -> str:
        """
        flameshot screenshot tool.
        Installed (confirmed by diagnostic).
        """
        env = dict(os.environ)

        for args in [
            ["flameshot", "full", "--path", path],
            ["flameshot", "screen", "--path", path],
            ["flameshot", "full", "-p", path],
        ]:
            r = subprocess.run(
                args,
                capture_output=True,
                timeout=12,
                env=env,
            )
            if r.returncode == 0 and Path(path).exists():
                if Path(path).stat().st_size > 100:
                    return path

        # Try with XWayland
        env_x = _xwayland_env()
        r = subprocess.run(
            ["flameshot", "full", "--path", path],
            capture_output=True,
            timeout=12,
            env=env_x,
        )
        return path if (
            r.returncode == 0 and
            Path(path).exists() and
            Path(path).stat().st_size > 100
        ) else ""

    # ════════════════════════════════════════════════════════════════════
    #  SCREENSHOT METHOD 6 — PIL via XWayland subprocess
    # ════════════════════════════════════════════════════════════════════
    def _ss_pil_xwayland(self, path: str) -> str:
        """
        PIL ImageGrab via XWayland.
        PIL installed (confirmed by diagnostic).
        Runs in subprocess to isolate environment.
        """
        abs_path = str(Path(path).resolve())

        script = (
            "import os\n"
            "os.environ['DISPLAY'] = ':0'\n"
            "os.environ['WAYLAND_DISPLAY'] = ''\n"
            "from PIL import ImageGrab\n"
            "img = ImageGrab.grab()\n"
            f"img.save(r'{abs_path}', 'PNG')\n"
            "print(f'ok:{{img.size}}')\n"
        )

        env = _xwayland_env()
        r   = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )

        return abs_path if (
            "ok:" in r.stdout and
            Path(abs_path).exists() and
            Path(abs_path).stat().st_size > 100
        ) else ""

    # ════════════════════════════════════════════════════════════════════
    #  SCREENSHOT METHOD 7 — scrot direct (no env override)
    # ════════════════════════════════════════════════════════════════════
    def _ss_scrot_direct(self, path: str) -> str:
        """scrot with current environment — bare fallback."""
        r = subprocess.run(
            ["scrot", path],
            capture_output=True,
            timeout=12,
        )
        return path if (
            r.returncode == 0 and
            Path(path).exists() and
            Path(path).stat().st_size > 100
        ) else ""

    # ════════════════════════════════════════════════════════════════════
    #  SCREENSHOT METHOD 8 — gdbus (blocked on this system)
    # ════════════════════════════════════════════════════════════════════
    def _ss_gdbus(self, path: str) -> str:
        """
        GNOME Shell DBus screenshot.
        DISABLED: Returns AccessDenied on this system.
        Kept for future reference.
        """
        # Known result: GDBus.Error:org.freedesktop.DBus.Error.AccessDenied
        # Screenshot is not allowed (GNOME security policy)
        return ""

    # ════════════════════════════════════════════════════════════════════
    #  TEST ALL METHODS
    # ════════════════════════════════════════════════════════════════════
    def test_screenshot(self) -> str:
        """
        Test all screenshot methods and cache the best one.
        Returns a formatted status report.
        Called by action=install or action=status.
        """
        test_dir = Path.home() / ".jarvis" / "ict_trader" / "screenshots"
        test_dir.mkdir(parents=True, exist_ok=True)

        self.log("Testing all screenshot methods...")

        methods = [
            self._ss_scrot_xwayland,
            self._ss_mss_xwayland,
            self._ss_xwd_xwayland,
            self._ss_spectacle,
            self._ss_flameshot,
            self._ss_pil_xwayland,
            self._ss_scrot_direct,
        ]

        results = []
        first_working = None

        for method in methods:
            test_path = str(test_dir / f"ss_test_{method.__name__}.png")
            # Clean up previous test
            try:
                Path(test_path).unlink(missing_ok=True)
            except Exception:
                pass

            try:
                result = method(test_path)
                p = Path(test_path)
                if result and p.exists() and p.stat().st_size > 3000:
                    size = p.stat().st_size
                    results.append(f"✅ {method.__name__}: {size:,} bytes")
                    if first_working is None:
                        first_working = method
                        self._best_ss_method = method
                        self.log(f"✅ Best method set: {method.__name__}")
                elif result and p.exists():
                    results.append(
                        f"⚠️ {method.__name__}: "
                        f"too small ({p.stat().st_size} bytes)"
                    )
                else:
                    results.append(f"❌ {method.__name__}: no output")
            except Exception as e:
                results.append(f"❌ {method.__name__}: {str(e)[:80]}")

        report = "\n".join(results)
        if first_working:
            report += f"\n\n✅ Active method: {first_working.__name__}"
        else:
            report += "\n\n❌ No working screenshot method found!"

        self.log(f"Screenshot test:\n{report}")
        return report

    # ════════════════════════════════════════════════════════════════════
    #  INSTALL TOOLS
    # ════════════════════════════════════════════════════════════════════
    def install_screenshot_tools(self) -> str:
        """
        Install screenshot tools appropriate for this system.
        scrot is already installed — this ensures all backups are available.
        """
        results = []

        # apt packages
        apt_pkgs = ["scrot", "imagemagick", "x11-apps", "flameshot"]
        for pkg in apt_pkgs:
            try:
                r = subprocess.run(
                    ["sudo", "apt", "install", "-y", "--no-install-recommends", pkg],
                    capture_output=True,
                    timeout=90,
                )
                status = "✅" if r.returncode == 0 else "❌"
                results.append(f"{status} {pkg}")
                self.log(
                    f"{'Installed' if r.returncode == 0 else 'Failed'}: {pkg}"
                )
            except Exception as e:
                results.append(f"❌ {pkg}: {e}")

        # pip packages
        pip_pkgs = ["mss", "pillow", "pyscreenshot"]
        for pkg in pip_pkgs:
            try:
                r = subprocess.run(
                    [sys.executable, "-m", "pip", "install", pkg, "-q"],
                    capture_output=True,
                    timeout=60,
                )
                status = "✅" if r.returncode == 0 else "❌"
                results.append(f"{status} {pkg} (pip)")
            except Exception as e:
                results.append(f"❌ {pkg} (pip): {e}")

        # Run test after install
        results.append("\n--- Screenshot Method Test ---")
        test_result = self.test_screenshot()
        results.append(test_result)

        return "\n".join(results)

    # ════════════════════════════════════════════════════════════════════
    #  OPEN TRADINGVIEW
    # ════════════════════════════════════════════════════════════════════
    def open_tradingview(self, symbol: str = "") -> str:
        """Open TradingView chart in browser."""
        url = self._tv_url
        if symbol:
            clean = symbol.upper().replace("/", "")
            url   = f"https://www.tradingview.com/chart/?symbol={clean}"

        self.log(f"Opening: {url}")

        browsers = [
            self.browser,
            "firefox",
            "google-chrome",
            "chromium",
            "chromium-browser",
            "brave-browser",
        ]

        opened = False
        for b in browsers:
            try:
                subprocess.Popen(
                    [b, "--new-window", url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.browser = b
                opened       = True
                self.log(f"Opened with: {b}")
                break
            except FileNotFoundError:
                continue

        if not opened:
            self.log("❌ No browser found")
            return "No browser found — install firefox or chrome"

        # Wait for browser + page to load
        time.sleep(6)
        self._focus_tv_window()
        time.sleep(2)
        self._ready = True

        return f"TradingView opened: {symbol or 'default chart'}"

    # ════════════════════════════════════════════════════════════════════
    #  FOCUS WINDOW
    # ════════════════════════════════════════════════════════════════════
    def _focus_tv_window(self):
        """
        Focus the TradingView browser window.
        Uses xdotool via XWayland (wmctrl not available on this system).
        """
        # Method 1: xdotool search by name (works via XWayland on GNOME)
        for search_term in ["TradingView", "tradingview", "Firefox", "Chrome"]:
            try:
                r = subprocess.run(
                    ["xdotool", "search", "--name", search_term],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                wids = [
                    w for w in r.stdout.strip().split("\n")
                    if w.strip()
                ]
                if wids:
                    # Activate the last matching window
                    subprocess.run(
                        ["xdotool", "windowactivate", "--sync", wids[-1]],
                        capture_output=True,
                        timeout=4,
                    )
                    time.sleep(0.5)
                    return
            except Exception:
                continue

        # Method 2: xdotool search by class (browser windows)
        for wm_class in ["Navigator", "firefox", "chromium", "brave-browser"]:
            try:
                r = subprocess.run(
                    ["xdotool", "search", "--class", wm_class],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                wids = [w for w in r.stdout.strip().split("\n") if w.strip()]
                if wids:
                    subprocess.run(
                        ["xdotool", "windowactivate", "--sync", wids[-1]],
                        capture_output=True,
                        timeout=4,
                    )
                    time.sleep(0.5)
                    return
            except Exception:
                continue

        # Method 3: xdotool focus currently active window
        try:
            subprocess.run(
                ["xdotool", "getactivewindow", "windowfocus"],
                capture_output=True,
                timeout=4,
            )
            time.sleep(0.3)
        except Exception:
            pass

        # Method 4: GNOME Shell via gdbus eval (no wmctrl available)
        try:
            subprocess.run(
                [
                    "gdbus", "call",
                    "--session",
                    "--dest",        "org.gnome.Shell",
                    "--object-path", "/org/gnome/Shell",
                    "--method",      "org.gnome.Shell.Eval",
                    (
                        "global.get_window_actors()"
                        ".map(a=>a.meta_window)"
                        ".filter(w=>w.get_title().includes('TradingView'))"
                        ".forEach(w=>w.activate(0))"
                    ),
                ],
                capture_output=True,
                timeout=4,
            )
            time.sleep(0.4)
        except Exception:
            pass

    # ════════════════════════════════════════════════════════════════════
    #  SYMBOL CHANGE
    # ════════════════════════════════════════════════════════════════════
    def change_symbol(self, symbol: str) -> str:
        """
        Change the TradingView chart symbol.
        Uses Ctrl+K (TradingView universal search shortcut).
        """
        self._focus_tv_window()
        time.sleep(0.6)

        clean = symbol.upper().replace("/", "").replace(" ", "")
        self.log(f"Changing symbol → {clean}")

        try:
            # Open symbol search
            pyautogui.hotkey("ctrl", "k")
            time.sleep(0.9)

            # Clear existing text
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.1)
            pyautogui.press("delete")
            time.sleep(0.1)

            # Type new symbol
            pyautogui.typewrite(clean, interval=0.06)
            time.sleep(1.8)

            # Select first result
            pyautogui.press("enter")
            time.sleep(2.5)

            self.log(f"Symbol → {clean}")
            return f"Symbol changed to: {clean}"

        except Exception as e:
            self.log(f"change_symbol error: {e}")
            return f"Symbol change attempted: {clean}"

    # ════════════════════════════════════════════════════════════════════
    #  TIMEFRAME CHANGE
    # ════════════════════════════════════════════════════════════════════
    def change_timeframe(self, tf: str) -> str:
        """
        Change the TradingView chart timeframe.
        Clicks the timeframe button in the TV toolbar.
        """
        self._focus_tv_window()
        time.sleep(0.5)

        # Log TV internal code
        tv_code = TV_TIMEFRAMES.get(tf, tf)
        print(tv_code)

        screen_w, screen_h = pyautogui.size()

        # TradingView timeframe toolbar Y position
        # Typically at ~6-7% from top of screen
        tf_bar_y = int(screen_h * 0.064)

        # Approximate X positions of TF buttons (% of screen width)
        # These may need adjustment based on your TV layout/zoom
        tf_x_map = {
            "1m":  0.085, "3m":  0.100, "5m":  0.115,
            "15m": 0.130, "30m": 0.145,
            "1h":  0.160, "2h":  0.175, "4h":  0.190,
            "1d":  0.205, "1w":  0.220, "1M":  0.235,
        }

        if tf in tf_x_map:
            x = int(screen_w * tf_x_map[tf])
            self.log(
                f"Clicking TF button: {tf} at "
                f"({x}, {tf_bar_y})"
            )
            pyautogui.click(x, tf_bar_y)
            time.sleep(0.4)
        else:
            self.log(f"TF {tf} not in click map — using fallback")
            # Fallback: try clicking the current TF display to open selector
            center_x = int(screen_w * 0.19)
            pyautogui.click(center_x, tf_bar_y)
            time.sleep(0.4)

        time.sleep(1.5)
        self.log(f"Timeframe → {tf}")
        return f"Timeframe: {tf}"

    # ════════════════════════════════════════════════════════════════════
    #  UTILITIES
    # ════════════════════════════════════════════════════════════════════
    def is_tv_open(self) -> bool:
        """Check if TradingView is open in any browser window."""
        # Check via xdotool (works via XWayland)
        for search_term in ["TradingView", "tradingview"]:
            try:
                r = subprocess.run(
                    ["xdotool", "search", "--name", search_term],
                    capture_output=True,
                    text=True,
                    timeout=4,
                )
                if r.stdout.strip():
                    return True
            except Exception:
                continue

        # Check via process list as fallback
        try:
            r = subprocess.run(
                ["pgrep", "-f", "tradingview"],
                capture_output=True,
                timeout=4,
            )
            if r.returncode == 0:
                return True
        except Exception:
            pass

        return False

    def reset_chart_view(self):
        """Reset chart to auto-fit view."""
        self._focus_tv_window()
        pyautogui.hotkey("alt", "r")
        time.sleep(0.5)

    def scroll_chart(self, direction: str = "left", amount: int = 10):
        """Scroll chart left or right."""
        self._focus_tv_window()
        key = "left" if direction == "left" else "right"
        for _ in range(amount):
            pyautogui.press(key)
            time.sleep(0.02)

    def zoom_chart(self, direction: str = "in", amount: int = 3):
        """Zoom chart in or out using scroll wheel."""
        self._focus_tv_window()
        for _ in range(amount):
            if direction == "in":
                pyautogui.scroll(0, 3)
            else:
                pyautogui.scroll(0, -3)
            time.sleep(0.1)

    def click_chart_at(self, x_pct: float, y_pct: float):
        """Click on chart at percentage position of screen."""
        self._focus_tv_window()
        sw, sh = pyautogui.size()
        pyautogui.click(int(sw * x_pct), int(sh * y_pct))
        time.sleep(0.2)

    def wait_for_chart_load(self, timeout: int = 8):
        """Wait for chart to fully load."""
        time.sleep(min(timeout, 6))
        self._ready = True

    def get_current_price(self) -> float:
        """
        Get current price from chart.
        Returns 0.0 — price is read from screenshot by Gemini Vision.
        """
        return 0.0

    def check_tools(self) -> dict:
        """Check which screenshot tools are available on this system."""
        tools = {}

        # Binary tools
        for tool in [
            "scrot", "grim", "flameshot", "spectacle",
            "gnome-screenshot", "xwd", "import",
            "xdotool", "wmctrl", "gdbus",
        ]:
            try:
                r = subprocess.run(
                    ["which", tool],
                    capture_output=True,
                    timeout=3,
                )
                tools[tool] = r.returncode == 0
            except Exception:
                tools[tool] = False

        # Python packages
        for pkg in ["mss", "PIL", "pyautogui", "pyscreenshot"]:
            try:
                __import__(pkg if pkg != "PIL" else "PIL.Image")
                tools[pkg] = True
            except ImportError:
                tools[pkg] = False

        return tools