#!/usr/bin/env python3
"""
doctor.py — VINCEVISION / JARVIS setup checker
───────────────────────────────────────────────
Run this right after cloning to see exactly what's ready and what's missing:

    python doctor.py            # report
    python doctor.py --fix      # create dirs + copy config templates
    python doctor.py --json     # machine-readable report

Stdlib-only: works before `pip install -r requirements.txt`.
Exit code 0 = core ready, 1 = something essential is missing.
"""

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MIN_PYTHON = (3, 10)
RECOMMENDED_PYTHON = (3, 11)

# Directories JARVIS writes to at runtime (all gitignored where sensitive).
RUNTIME_DIRS = ["config", "memory", "logs", "reports", "browser_profiles"]

# Config templates shipped with the repo → the real (gitignored) file.
TEMPLATES = {
    "api_keys.example.json": "api_keys.json",
    "email_config.example.json": "email_config.json",
    "telegram_config.example.json": "telegram_config.json",
    "notion_config.example.json": "notion_config.json",
    "scope.example.json": "scope.json",
}

# (import name, pip name, essential?) — checked with find_spec, never imported.
DEPENDENCIES = [
    ("google.genai", "google-genai", True),
    ("sounddevice", "sounddevice", True),
    ("PyQt6", "pyqt6", True),
    ("requests", "requests", True),
    ("playwright", "playwright", False),
    ("psutil", "psutil", False),
    ("googleapiclient", "google-api-python-client", False),
    ("google_auth_oauthlib", "google-auth-oauthlib", False),
    ("imapclient", "imapclient", False),
]

PLACEHOLDER_MARKERS = ("YOUR_", "_HERE", "CHANGE_ME", "example.com")


def _check(name, status, detail, fix=""):
    return {"name": name, "status": status, "detail": detail, "fix": fix}


def check_python():
    v = sys.version_info
    if (v.major, v.minor) < MIN_PYTHON:
        return _check("python", "fail",
                      f"Python {v.major}.{v.minor} found; {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required.",
                      "Install Python 3.11 or 3.12 and recreate your virtualenv.")
    if (v.major, v.minor) < RECOMMENDED_PYTHON:
        return _check("python", "warn",
                      f"Python {v.major}.{v.minor} works, but 3.11+ is recommended (CI tests 3.11/3.12).")
    return _check("python", "ok", f"Python {v.major}.{v.minor}.{v.micro}")


def check_assets(base_dir: Path):
    checks = []
    for asset in ("main.py", "face.png", "core/prompt.txt", "requirements.txt"):
        p = base_dir / asset
        checks.append(_check(f"asset:{asset}", "ok" if p.exists() else "fail",
                             "present" if p.exists() else "missing from checkout",
                             "" if p.exists() else "Re-clone the repository; this file is tracked in git."))
    return checks


def check_dirs(base_dir: Path):
    checks = []
    for d in RUNTIME_DIRS:
        p = base_dir / d
        checks.append(_check(f"dir:{d}", "ok" if p.is_dir() else "warn",
                             "present" if p.is_dir() else "will be created on first run",
                             "" if p.is_dir() else "python doctor.py --fix"))
    return checks


def _is_placeholder(value) -> bool:
    if not isinstance(value, str) or not value.strip():
        return True
    return any(m in value for m in PLACEHOLDER_MARKERS)


def check_api_keys(base_dir: Path):
    path = base_dir / "config" / "api_keys.json"
    if not path.exists():
        return _check("api_keys", "fail", "config/api_keys.json not found.",
                      "python doctor.py --fix, then paste your keys into config/api_keys.json")
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return _check("api_keys", "fail", f"config/api_keys.json is not valid JSON: {e}",
                      "Fix the JSON or re-copy from config/api_keys.example.json")
    gemini = cfg.get("gemini_api_key", "")
    groq = cfg.get("groq_api_key", "") or cfg.get("GROQ_API_KEY", "")
    if _is_placeholder(gemini):
        return _check("api_keys", "fail",
                      "Gemini API key is missing or still a placeholder.",
                      "Get a free key at https://aistudio.google.com/apikey and set gemini_api_key")
    if _is_placeholder(groq):
        return _check("api_keys", "warn",
                      "Gemini key set; Groq fallback key missing (optional but recommended).",
                      "Get a free key at https://console.groq.com/keys and set groq_api_key")
    return _check("api_keys", "ok", "Gemini + Groq keys configured")


def check_optional_configs(base_dir: Path):
    checks = []
    optional = {
        "google_client_secret.json": "Google cloud agents (Gmail/Calendar/Docs/Drive) — see docs/cloud_integrations.md",
        "notion_config.json": "Notion agent — see docs/cloud_integrations.md",
        "email_config.json": "IMAP email fallback — see docs/email_browser.md",
        "telegram_config.json": "Telegram bot remote control",
        "scope.json": "Pentest scope/RoE — see docs/pentest_kit.md",
    }
    for fname, purpose in optional.items():
        p = base_dir / "config" / fname
        if not p.exists():
            checks.append(_check(f"config:{fname}", "info", f"not set up (optional): {purpose}"))
        elif fname != "google_client_secret.json":
            try:
                cfg = json.loads(p.read_text(encoding="utf-8"))
                filled = any(not _is_placeholder(v) for v in cfg.values()
                             if isinstance(v, str) and v)
                checks.append(_check(f"config:{fname}",
                                     "ok" if filled else "warn",
                                     "configured" if filled else "still contains placeholder values",
                                     "" if filled else f"Edit config/{fname}"))
            except Exception:
                checks.append(_check(f"config:{fname}", "warn", "present but not valid JSON"))
        else:
            checks.append(_check(f"config:{fname}", "ok", "present"))
    return checks


def check_dependencies(finder=None):
    """finder injectable for tests; defaults to importlib.util.find_spec."""
    find = finder or importlib.util.find_spec
    checks = []
    for import_name, pip_name, essential in DEPENDENCIES:
        try:
            found = find(import_name) is not None
        except Exception:
            found = False
        if found:
            checks.append(_check(f"dep:{pip_name}", "ok", "installed"))
        else:
            checks.append(_check(
                f"dep:{pip_name}", "fail" if essential else "warn",
                "not installed" + (" (required to start JARVIS)" if essential else " (optional feature)"),
                f"pip install {pip_name}  (or: pip install -r requirements.txt)"))
    return checks


def run_all(base_dir=None, finder=None):
    base = Path(base_dir) if base_dir else BASE_DIR
    checks = [check_python()]
    checks += check_assets(base)
    checks += check_dirs(base)
    checks.append(check_api_keys(base))
    checks += check_optional_configs(base)
    checks += check_dependencies(finder)
    return checks


def apply_fixes(base_dir=None):
    """Create runtime dirs and copy config templates that don't exist yet."""
    base = Path(base_dir) if base_dir else BASE_DIR
    actions = []
    for d in RUNTIME_DIRS:
        p = base / d
        if not p.is_dir():
            p.mkdir(parents=True, exist_ok=True)
            actions.append(f"created {d}/")
    cfg_dir = base / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    for template, real in TEMPLATES.items():
        src, dst = cfg_dir / template, cfg_dir / real
        if src.exists() and not dst.exists():
            shutil.copyfile(src, dst)
            actions.append(f"created config/{real} from template — edit it with your values")
    return actions


ICONS = {"ok": "✅", "warn": "⚠️ ", "fail": "❌", "info": "ℹ️ "}


def print_report(checks):
    counts = {"ok": 0, "warn": 0, "fail": 0, "info": 0}
    print("🩺 VINCEVISION / JARVIS setup doctor\n" + "─" * 46)
    for c in checks:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
        print(f"{ICONS.get(c['status'], '?')} {c['name']}: {c['detail']}")
        if c.get("fix") and c["status"] in ("fail", "warn"):
            print(f"     ↳ {c['fix']}")
    print("─" * 46)
    print(f"{counts['ok']} ok · {counts['warn']} warnings · {counts['fail']} blocking · {counts['info']} optional")
    if counts["fail"] == 0:
        print("\n🚀 Core setup looks good. Start JARVIS with: python main.py")
    else:
        print("\n🔧 Fix the ❌ items above, then re-run: python doctor.py")
    return counts["fail"]


def main(argv=None):
    parser = argparse.ArgumentParser(description="JARVIS setup checker")
    parser.add_argument("--fix", action="store_true",
                        help="create runtime dirs and copy config templates")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    if args.fix:
        actions = apply_fixes()
        if not args.json:
            for a in actions:
                print(f"🔧 {a}")
            if not actions:
                print("Nothing to fix — dirs and configs already in place.")

    checks = run_all()
    if args.json:
        print(json.dumps(checks, indent=2))
        return 1 if any(c["status"] == "fail" for c in checks) else 0
    return 1 if print_report(checks) else 0


if __name__ == "__main__":
    sys.exit(main())
