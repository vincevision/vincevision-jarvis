# core/dependency_manager.py
"""
JARVIS Dependency Manager
─────────────────────────
Auto-installs missing Python packages on launch.
Tracks dependencies per agent.
Updates requirements.txt automatically.
Handles Kali/Debian PEP 668 (--break-system-packages).
"""

import os
import sys
import json
import subprocess
import importlib
import platform
from pathlib  import Path
from datetime import datetime


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR         = _get_base_dir()
REQUIREMENTS_FILE = BASE_DIR / "requirements.txt"
DEPS_REGISTRY     = BASE_DIR / "config" / "dependencies.json"
LOG_FILE          = BASE_DIR / "logs" / "dependencies.log"

DEPS_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


# ═════════════════════════════════════════════
# DEPENDENCY REGISTRY
# ═════════════════════════════════════════════
# Maps agent → required packages
# Format:
#   "agent_name": {
#       "packages":     ["package_name>=version"],
#       "import_names": {"package_name": "import_name"},  # if different
#       "system_deps":  {"linux": ["apt-package"]},        # optional
#       "optional":     bool,
#   }

CORE_DEPENDENCIES = {
    "core": {
        "packages": [
            "google-genai>=0.3.0",
            "sounddevice>=0.4.6",
            "Pillow>=10.0.0",
            "requests>=2.31.0",
        ],
        "import_names": {
            "google-genai": "google.genai",
            "Pillow":       "PIL",
        },
    },

    "number_tracer": {
        "packages": [
            "phonenumbers>=8.13.0",
            "beautifulsoup4>=4.12.0",
            "telethon>=1.34.0",
        ],
        "import_names": {
            "beautifulsoup4": "bs4",
        },
    },

    "trading_agent": {
        "packages": [
            "MetaTrader5>=5.0.45",
            "pandas>=2.0.0",
            "numpy>=1.24.0",
            "ccxt>=4.0.0",
        ],
        "import_names": {
            "MetaTrader5": "MetaTrader5",
        },
        "optional": True,  # Don't auto-install at startup
    },

    "tiktok_agent": {
        "packages": [
            "selenium>=4.15.0",
            "undetected-chromedriver>=3.5.0",
        ],
        "import_names": {
            "undetected-chromedriver": "undetected_chromedriver",
        },
    },

    "telegram_bot": {
        "packages": [
            "python-telegram-bot>=20.0",
        ],
        "import_names": {
            "python-telegram-bot": "telegram",
        },
    },

    "email_agent": {
        "packages": [
            "imapclient>=3.0.0",
        ],
    },

    "security_agent": {
        "packages": [
            "scapy>=2.5.0",
            "python-nmap>=0.7.1",
        ],
        "import_names": {
            "python-nmap": "nmap",
        },
    },

    "file_processor": {
        "packages": [
            "PyPDF2>=3.0.0",
            "python-docx>=1.0.0",
            "openpyxl>=3.1.0",
            "pytesseract>=0.3.10",
        ],
        "import_names": {
            "python-docx": "docx",
            "PyPDF2":      "PyPDF2",
        },
    },

    "smart_home": {
        "packages": [
            "paho-mqtt>=1.6.0",
        ],
        "import_names": {
            "paho-mqtt": "paho.mqtt.client",
        },
        "optional": True,
    },

    "computer_control": {
        "packages": [
            "pyautogui>=0.9.54",
            "pyperclip>=1.8.2",
        ],
    },

    "screen_processor": {
        "packages": [
            "opencv-python>=4.8.0",
            "mss>=9.0.0",
        ],
        "import_names": {
            "opencv-python": "cv2",
        },
    },

    "browser_control": {
        "packages": [
            "playwright>=1.40.0",
        ],
    },
}


# ═════════════════════════════════════════════
# LOGGING
# ═════════════════════════════════════════════
def _log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line      = f"[{timestamp}] {msg}\n"
    print(f"[Deps] {msg}")
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


# ═════════════════════════════════════════════
# REGISTRY PERSISTENCE
# ═════════════════════════════════════════════
def _load_registry() -> dict:
    """Load custom dependency registry (merged with hardcoded one)."""
    if not DEPS_REGISTRY.exists():
        return CORE_DEPENDENCIES.copy()

    try:
        with open(DEPS_REGISTRY, "r", encoding="utf-8") as f:
            custom = json.load(f)
        # Merge custom over core
        merged = CORE_DEPENDENCIES.copy()
        merged.update(custom)
        return merged
    except Exception as e:
        _log(f"Failed to load registry: {e}")
        return CORE_DEPENDENCIES.copy()


def _save_registry(registry: dict):
    """Save current registry to JSON for persistence."""
    try:
        with open(DEPS_REGISTRY, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2)
    except Exception as e:
        _log(f"Failed to save registry: {e}")


# ═════════════════════════════════════════════
# PACKAGE CHECKS
# ═════════════════════════════════════════════
def _is_installed(pkg_spec: str, import_name: str = None) -> bool:
    """Check if a package is installed."""
    pkg_name = pkg_spec.split(">=")[0].split("==")[0].split("<")[0].strip()

    if not import_name:
        # Try common name conversions
        import_name = pkg_name.replace("-", "_").lower()

    try:
        importlib.import_module(import_name)
        return True
    except ImportError:
        return False
    except Exception:
        return False


def _detect_pip_command() -> list:
    """Detect the right pip command for this system."""
    return [sys.executable, "-m", "pip"]


def _is_kali_or_debian() -> bool:
    """Check if running on Kali/Debian (needs --break-system-packages)."""
    try:
        if Path("/etc/os-release").exists():
            content = Path("/etc/os-release").read_text().lower()
            return any(d in content for d in ["kali", "debian", "ubuntu"])
    except Exception:
        pass
    return False


def _needs_break_system_packages() -> bool:
    """Check if pip needs --break-system-packages flag."""
    if not _is_kali_or_debian():
        return False
    # Test by trying a no-op install
    try:
        result = subprocess.run(
            [*_detect_pip_command(), "install", "--dry-run", "pip"],
            capture_output=True, text=True, timeout=10,
        )
        return "externally-managed-environment" in (result.stderr or "")
    except Exception:
        return True  # safer default on Kali


# ═════════════════════════════════════════════
# INSTALLER
# ═════════════════════════════════════════════
def install_package(pkg_spec: str, quiet: bool = False) -> bool:
    """Install a single package."""
    pip_cmd = _detect_pip_command()
    cmd     = [*pip_cmd, "install", pkg_spec, "--upgrade"]

    if _needs_break_system_packages():
        cmd.append("--break-system-packages")

    if quiet:
        cmd.append("-q")

    _log(f"📦 Installing: {pkg_spec}")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            _log(f"✅ Installed: {pkg_spec}")
            return True
        else:
            _log(f"❌ Failed: {pkg_spec} — {result.stderr[:200]}")
            return False
    except subprocess.TimeoutExpired:
        _log(f"⏱️ Timeout installing: {pkg_spec}")
        return False
    except Exception as e:
        _log(f"❌ Error installing {pkg_spec}: {e}")
        return False


def install_packages(pkg_specs: list, quiet: bool = False) -> dict:
    """Install multiple packages, returns {pkg: success}."""
    results = {}
    for pkg in pkg_specs:
        results[pkg] = install_package(pkg, quiet=quiet)
    return results


# ═════════════════════════════════════════════
# REQUIREMENTS.TXT MANAGEMENT
# ═════════════════════════════════════════════
def _read_requirements() -> list:
    """Read existing requirements.txt entries."""
    if not REQUIREMENTS_FILE.exists():
        return []

    lines = []
    try:
        with open(REQUIREMENTS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    lines.append(stripped)
    except Exception as e:
        _log(f"Failed to read requirements: {e}")
    return lines


def _write_requirements(packages: list):
    """Write requirements.txt with header."""
    header = (
        "# JARVIS — Auto-managed requirements\n"
        f"# Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        "# Edit this file to lock specific versions\n"
        "\n"
    )
    try:
        with open(REQUIREMENTS_FILE, "w", encoding="utf-8") as f:
            f.write(header)
            for pkg in sorted(set(packages), key=str.lower):
                f.write(f"{pkg}\n")
    except Exception as e:
        _log(f"Failed to write requirements: {e}")


def _normalize_pkg_name(spec: str) -> str:
    """Get just the package name from a spec like 'numpy>=1.24.0'."""
    return spec.split(">=")[0].split("==")[0].split("<")[0].strip().lower()


def update_requirements_file(quiet: bool = True):
    """Sync requirements.txt with the dependency registry."""
    registry = _load_registry()

    # Collect all packages from registry
    all_packages = set()
    for agent, info in registry.items():
        for pkg in info.get("packages", []):
            all_packages.add(pkg)

    # Read existing
    existing = _read_requirements()
    existing_names = {_normalize_pkg_name(p): p for p in existing}

    # Merge — keep existing version if user has pinned it, add new ones
    final = list(existing)
    added = []
    for pkg in all_packages:
        name = _normalize_pkg_name(pkg)
        if name not in existing_names:
            final.append(pkg)
            added.append(pkg)

    if added:
        _write_requirements(final)
        if not quiet:
            _log(f"📝 Updated requirements.txt: added {len(added)} packages")
            for p in added:
                _log(f"   + {p}")
    elif not quiet:
        _log("📝 requirements.txt is up to date")

    return added


def add_dependency(agent: str, packages: list, import_names: dict = None,
                   optional: bool = False):
    """
    Register new dependencies for a tool/agent.
    Use this in NEW agents like:
        from core.dependency_manager import add_dependency
        add_dependency("my_new_agent", ["fancy-lib>=1.0"])
    """
    registry = _load_registry()

    if agent not in registry:
        registry[agent] = {"packages": [], "import_names": {}, "optional": optional}

    # Add packages (no duplicates)
    existing_names = {_normalize_pkg_name(p) for p in registry[agent]["packages"]}
    for pkg in packages:
        if _normalize_pkg_name(pkg) not in existing_names:
            registry[agent]["packages"].append(pkg)

    # Add import names
    if import_names:
        registry[agent].setdefault("import_names", {}).update(import_names)

    _save_registry(registry)
    update_requirements_file(quiet=True)


# ═════════════════════════════════════════════
# CHECK & INSTALL FOR AGENT
# ═════════════════════════════════════════════
def check_agent_deps(agent: str) -> dict:
    """Check which dependencies of an agent are installed."""
    registry = _load_registry()
    info     = registry.get(agent, {})

    packages     = info.get("packages", [])
    import_names = info.get("import_names", {})

    results = {"installed": [], "missing": []}
    for pkg in packages:
        pkg_name = _normalize_pkg_name(pkg)
        # Check via custom import name first
        import_name = None
        for orig, mapped in import_names.items():
            if _normalize_pkg_name(orig) == pkg_name:
                import_name = mapped
                break

        if _is_installed(pkg, import_name):
            results["installed"].append(pkg)
        else:
            results["missing"].append(pkg)

    return results


def ensure_agent_deps(agent: str, auto_install: bool = True,
                     quiet: bool = False) -> bool:
    """
    Make sure all deps for an agent are installed.
    Returns True if everything is ready, False otherwise.
    """
    status = check_agent_deps(agent)

    if not status["missing"]:
        return True

    if not auto_install:
        if not quiet:
            _log(f"⚠️ {agent} is missing: {', '.join(status['missing'])}")
        return False

    if not quiet:
        _log(f"📦 Installing {len(status['missing'])} missing deps for {agent}...")

    results = install_packages(status["missing"], quiet=quiet)
    return all(results.values())


# ═════════════════════════════════════════════
# STARTUP CHECK
# ═════════════════════════════════════════════
def startup_check(install_optional: bool = False, quiet: bool = False) -> dict:
    """
    Called on JARVIS startup to install all missing deps.
    Returns: {"installed": [], "failed": [], "skipped": []}
    """
    registry = _load_registry()

    summary = {
        "installed":     [],
        "failed":        [],
        "skipped":       [],
        "already_ok":    [],
    }

    if not quiet:
        _log("🔍 Checking dependencies...")

    # First, sync requirements.txt
    added = update_requirements_file(quiet=True)
    if added and not quiet:
        _log(f"📝 Added {len(added)} new packages to requirements.txt")

    # Check each agent
    all_missing = {}
    for agent, info in registry.items():
        if info.get("optional") and not install_optional:
            continue

        status = check_agent_deps(agent)
        if status["missing"]:
            for pkg in status["missing"]:
                all_missing[pkg] = agent

    if not all_missing:
        if not quiet:
            _log("✅ All dependencies satisfied")
        return summary

    if not quiet:
        _log(f"📦 Found {len(all_missing)} missing packages — installing...")

    # Install all in one go for efficiency
    pip_cmd = _detect_pip_command()
    cmd     = [*pip_cmd, "install", *list(all_missing.keys()), "--upgrade"]
    if _needs_break_system_packages():
        cmd.append("--break-system-packages")
    if quiet:
        cmd.append("-q")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode == 0:
            summary["installed"] = list(all_missing.keys())
            if not quiet:
                _log(f"✅ Installed {len(all_missing)} packages")
        else:
            # Try one by one to identify which ones failed
            if not quiet:
                _log("⚠️ Bulk install failed, trying individually...")
            for pkg, agent in all_missing.items():
                if install_package(pkg, quiet=quiet):
                    summary["installed"].append(pkg)
                else:
                    summary["failed"].append(pkg)
    except Exception as e:
        _log(f"❌ Startup install failed: {e}")
        summary["failed"] = list(all_missing.keys())

    return summary


# ═════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════
def _print_status():
    """Print current dependency status."""
    registry = _load_registry()
    print("\n" + "═" * 60)
    print("📦 JARVIS DEPENDENCY STATUS")
    print("═" * 60 + "\n")

    for agent, info in registry.items():
        status = check_agent_deps(agent)
        total  = len(info.get("packages", []))
        ok     = len(status["installed"])

        emoji = "✅" if ok == total else "⚠️" if ok > 0 else "❌"
        opt   = " (optional)" if info.get("optional") else ""

        print(f"{emoji} {agent}: {ok}/{total}{opt}")
        for pkg in status["missing"]:
            print(f"     ❌ {pkg}")

    print("\n" + "═" * 60 + "\n")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="JARVIS Dependency Manager")
    parser.add_argument("--check",   action="store_true", help="Check status")
    parser.add_argument("--install", action="store_true", help="Install missing deps")
    parser.add_argument("--all",     action="store_true", help="Install optional too")
    parser.add_argument("--update",  action="store_true", help="Update requirements.txt")
    args = parser.parse_args()

    if args.check:
        _print_status()
    elif args.update:
        added = update_requirements_file(quiet=False)
        print(f"\n✅ Done — added {len(added)} new packages")
    elif args.install:
        result = startup_check(install_optional=args.all, quiet=False)
        print("\n" + "═" * 60)
        print("📊 SUMMARY")
        print("═" * 60)
        print(f"✅ Installed: {len(result['installed'])}")
        print(f"❌ Failed:    {len(result['failed'])}")
        if result["failed"]:
            for p in result["failed"]:
                print(f"   ❌ {p}")
        print()
    else:
        _print_status()
        print("Run with --install to install missing packages")
        print("Run with --all to include optional dependencies\n")