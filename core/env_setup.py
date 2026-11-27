# core/env_setup.py
"""
Environment setup for JARVIS.
Handles root execution with full browser support.
Safe for GitHub — fully dynamic, no hardcoded values.
Auto-runs on import.
"""

import os
import subprocess
from pathlib import Path


# ─────────────────────────────────────────────────────────────
# USER DETECTION
# ─────────────────────────────────────────────────────────────

def _get_real_user() -> str:
    """
    Get the real human user even when running as root.
    Tries multiple methods in order of reliability.
    """
    # Method 1: SUDO_USER (set when using sudo)
    sudo_user = os.environ.get("SUDO_USER", "")
    if sudo_user and sudo_user != "root":
        return sudo_user

    # Method 2: Who is on display :0
    try:
        result = subprocess.run(
            ["who"], capture_output=True, text=True, timeout=3
        )
        for line in result.stdout.split("\n"):
            if ":0" in line:
                user = line.split()[0]
                if user and user != "root":
                    return user
    except Exception:
        pass

    # Method 3: Check /run/user for non-root UIDs
    try:
        run_user = Path("/run/user")
        if run_user.exists():
            for uid_dir in sorted(run_user.iterdir()):
                try:
                    uid = int(uid_dir.name)
                    if uid >= 1000:
                        result = subprocess.run(
                            ["id", "-nu", str(uid)],
                            capture_output=True, text=True, timeout=3
                        )
                        user = result.stdout.strip()
                        if user and user != "root":
                            return user
                except Exception:
                    continue
    except Exception:
        pass

    # Method 4: logname
    try:
        result = subprocess.run(
            ["logname"], capture_output=True,
            text=True, timeout=3
        )
        user = result.stdout.strip()
        if user and user != "root":
            return user
    except Exception:
        pass

    # Method 5: users command
    try:
        result = subprocess.run(
            ["users"], capture_output=True,
            text=True, timeout=3
        )
        for user in result.stdout.strip().split():
            if user and user != "root":
                return user
    except Exception:
        pass

    # Method 6: /home directory scan
    try:
        home_dir = Path("/home")
        if home_dir.exists():
            users = [
                d.name for d in home_dir.iterdir()
                if d.is_dir() and d.name != "root"
            ]
            if users:
                return users[0]
    except Exception:
        pass

    # Fallback: current USER env
    return os.environ.get("USER", "vincent")


def _get_real_uid(username: str) -> str:
    """Get UID of a username dynamically."""
    # Method 1: id command
    try:
        result = subprocess.run(
            ["id", "-u", username],
            capture_output=True, text=True, timeout=3
        )
        uid = result.stdout.strip()
        if uid.isdigit():
            return uid
    except Exception:
        pass

    # Method 2: /run/user scan
    try:
        run_user = Path("/run/user")
        if run_user.exists():
            for uid_dir in sorted(run_user.iterdir()):
                try:
                    uid = int(uid_dir.name)
                    if uid >= 1000:
                        return str(uid)
                except Exception:
                    continue
    except Exception:
        pass

    # Method 3: /etc/passwd
    try:
        with open("/etc/passwd", "r") as f:
            for line in f:
                parts = line.strip().split(":")
                if len(parts) >= 3 and parts[0] == username:
                    return parts[2]
    except Exception:
        pass

    return "1000"


# ─────────────────────────────────────────────────────────────
# DISPLAY FIX
# ─────────────────────────────────────────────────────────────

def fix_display():
    """
    Ensure DISPLAY and Xauthority are set correctly.
    Handles root running on user's display.
    """
    import platform
    import glob

    if platform.system() != "Linux":
        return

    # Set DISPLAY if missing
    if not os.environ.get("DISPLAY"):
        os.environ["DISPLAY"] = ":0"
        print("[ENV] DISPLAY → :0")

    # Fix Xauthority for root
    if os.geteuid() == 0:
        real_user = _get_real_user()
        real_uid  = _get_real_uid(real_user)

        xauth_candidates = (
            glob.glob(f"/run/user/{real_uid}/.mutter-Xwaylandauth*") +
            glob.glob(f"/run/user/{real_uid}/.xauth*") +
            [
                f"/home/{real_user}/.Xauthority",
                f"/run/user/{real_uid}/gdm/Xauthority",
                "/root/.Xauthority",
            ]
        )

        for xauth in xauth_candidates:
            p = Path(xauth)
            if p.exists() and p.stat().st_size > 0:
                os.environ["XAUTHORITY"] = str(p)
                print(f"[ENV] Xauthority: {p}")
                break

        # Allow root to connect to X display
        try:
            subprocess.run(
                ["xhost", "+local:"],
                capture_output=True, timeout=2,
                env={**os.environ, "DISPLAY": ":0"}
            )
            subprocess.run(
                ["xhost", "+"],
                capture_output=True, timeout=2,
                env={**os.environ, "DISPLAY": ":0"}
            )
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────
# DBUS FIX
# ─────────────────────────────────────────────────────────────

def fix_dbus():
    """
    Fix DBus session for root process.
    Connects root to the real user's DBus session.
    This enables browser launch from root on Linux.
    """
    import platform

    if platform.system() != "Linux":
        return

    if os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        print("[ENV] DBus already set ✅")
        return

    real_user = _get_real_user()
    real_uid  = _get_real_uid(real_user)
    print(f"[ENV] Fixing DBus for {real_user} (uid={real_uid})")

    # ── Method 1: /run/user/UID/bus ───────────────
    # This is the most reliable on modern Linux/systemd
    bus_path = Path(f"/run/user/{real_uid}/bus")
    if bus_path.exists():
        val = f"unix:path=/run/user/{real_uid}/bus"
        os.environ["DBUS_SESSION_BUS_ADDRESS"] = val
        print(f"[ENV] DBus ✅ method 1: {val}")
        return

    # ── Method 2: Scan all /run/user/*/bus ────────
    try:
        run_user_dir = Path("/run/user")
        if run_user_dir.exists():
            for uid_dir in sorted(run_user_dir.iterdir()):
                try:
                    uid = int(uid_dir.name)
                    if uid >= 1000:
                        bus = uid_dir / "bus"
                        if bus.exists():
                            val = f"unix:path={bus}"
                            os.environ["DBUS_SESSION_BUS_ADDRESS"] = val
                            print(f"[ENV] DBus ✅ method 2: {val}")
                            return
                except Exception:
                    continue
    except Exception:
        pass

    # ── Method 3: Read from user's shell env ──────
    try:
        result = subprocess.run(
            ["su", real_user, "-c",
             "echo $DBUS_SESSION_BUS_ADDRESS"],
            capture_output=True, text=True, timeout=5
        )
        val = result.stdout.strip()
        if val and "unix:" in val:
            os.environ["DBUS_SESSION_BUS_ADDRESS"] = val
            print(f"[ENV] DBus ✅ method 3: {val[:60]}")
            return
    except Exception:
        pass

    # ── Method 4: Scan /proc for DBus address ─────
    try:
        for proc in sorted(Path("/proc").iterdir()):
            try:
                if not proc.name.isdigit():
                    continue
                environ_file = proc / "environ"
                if not environ_file.exists():
                    continue
                data = environ_file.read_bytes().decode(
                    errors="ignore"
                )
                if "DBUS_SESSION_BUS_ADDRESS" not in data:
                    continue
                for var in data.split("\0"):
                    if var.startswith("DBUS_SESSION_BUS_ADDRESS="):
                        val = var.split("=", 1)[1]
                        if val and "unix:" in val:
                            os.environ["DBUS_SESSION_BUS_ADDRESS"] = val
                            print(f"[ENV] DBus ✅ method 4: {val[:60]}")
                            return
            except Exception:
                continue
    except Exception:
        pass

    # ── Method 5: dbus-launch (last resort) ───────
    try:
        result = subprocess.run(
            ["dbus-launch", "--sh-syntax"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.split("\n"):
            if "DBUS_SESSION_BUS_ADDRESS" in line and "=" in line:
                val = (
                    line.split("=", 1)[1]
                    .strip().rstrip(";").strip("'").strip('"')
                )
                if val:
                    os.environ["DBUS_SESSION_BUS_ADDRESS"] = val
                    print(f"[ENV] DBus ✅ method 5: {val[:60]}")
                    return
    except Exception as e:
        print(f"[ENV] dbus-launch failed: {e}")

    print("[ENV] ⚠️  DBus not found — browsers may crash")


# ─────────────────────────────────────────────────────────────
# PLAYWRIGHT FIX
# ─────────────────────────────────────────────────────────────

def fix_playwright():
    """
    Find and set PLAYWRIGHT_BROWSERS_PATH dynamically.
    Works for any user, any machine.
    Safe for GitHub.
    """
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        print(
            f"[ENV] Playwright already set: "
            f"{os.environ['PLAYWRIGHT_BROWSERS_PATH']} ✅"
        )
        return

    real_user = _get_real_user()

    candidates = [
        # Real user cache (most likely location)
        Path(f"/home/{real_user}/.cache/ms-playwright"),
        # Current process home
        Path.home() / ".cache" / "ms-playwright",
        # Root cache
        Path("/root/.cache/ms-playwright"),
    ]

    # Scan all users in /home
    try:
        for user_dir in Path("/home").iterdir():
            p = user_dir / ".cache" / "ms-playwright"
            if p not in candidates:
                candidates.append(p)
    except Exception:
        pass

    # Try each candidate
    for path in candidates:
        try:
            if path.exists() and any(path.iterdir()):
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(path)
                print(f"[ENV] Playwright ✅ {path}")
                return
        except Exception:
            continue

    # Nothing found — auto install
    print("[ENV] Playwright chromium not found — installing...")
    install_path = Path(f"/home/{real_user}/.cache/ms-playwright")
    try:
        env = {
            **os.environ,
            "PLAYWRIGHT_BROWSERS_PATH": str(install_path),
            "HOME": f"/home/{real_user}",
        }
        subprocess.run(
            ["playwright", "install", "chromium"],
            check=True, timeout=120, env=env
        )
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(install_path)
        print(f"[ENV] Playwright installed ✅ {install_path}")
    except Exception as e:
        print(f"[ENV] Auto-install failed: {e}")
        print("[ENV] Run: playwright install chromium")


# ─────────────────────────────────────────────────────────────
# BROWSER ENV FIX
# ─────────────────────────────────────────────────────────────

def fix_browser_env():
    """
    Store real user info for browser_control.py.
    Used to launch browsers correctly from root.
    """
    import platform

    if platform.system() != "Linux":
        return

    if os.geteuid() != 0:
        return

    real_user = _get_real_user()
    real_uid  = _get_real_uid(real_user)
    real_home = f"/home/{real_user}"

    os.environ["JARVIS_REAL_USER"] = real_user
    os.environ["JARVIS_REAL_UID"]  = real_uid
    os.environ["JARVIS_REAL_HOME"] = real_home
    os.environ["JARVIS_IS_ROOT"]   = "1"

    print(
        f"[ENV] Browser env set: "
        f"user={real_user} uid={real_uid} home={real_home}"
    )


# ─────────────────────────────────────────────────────────────
# MAIN SETUP
# ─────────────────────────────────────────────────────────────

def setup_all():
    """
    Run all environment fixes.
    Called once at startup automatically.
    """
    import platform

    print("[ENV] Setting up JARVIS environment...")

    if platform.system() == "Linux":
        fix_display()
        fix_dbus()
        fix_browser_env()

    fix_playwright()

    # Final status report
    print(
        f"[ENV] ✅ Ready | "
        f"DISPLAY={os.environ.get('DISPLAY', 'NOT SET')} | "
        f"DBUS={'SET' if os.environ.get('DBUS_SESSION_BUS_ADDRESS') else 'NOT SET'} | "
        f"PW={os.environ.get('PLAYWRIGHT_BROWSERS_PATH', 'NOT SET')[:30]}"
    )


# Auto-run on import
setup_all()