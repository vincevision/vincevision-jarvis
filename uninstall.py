#!/usr/bin/env python3
"""
uninstall.py — VINCEVISION / JARVIS safe uninstaller
─────────────────────────────────────────────────────
Reverses everything install.sh / create_desktop_app.sh / setup.py created,
plus JARVIS's local secrets and runtime data. Designed to be safe:

  * DRY-RUN by default in non-interactive shells — nothing is deleted unless
    you confirm (or pass --yes).
  * NEVER deletes the repository source code or .git. It prints the manual
    command for that at the end, so you stay in control.
  * --keep-data preserves your secrets, memory, reports and browser sessions.
  * System files that need root are skipped with a ready-to-run sudo command
    when you're not root.

Usage:
    python uninstall.py                 # show plan, ask for confirmation
    python uninstall.py --dry-run       # show plan only, delete nothing
    python uninstall.py --yes           # actually remove (no prompt)
    python uninstall.py --keep-data     # remove integrations/caches, keep data
    python uninstall.py --integrations-only   # only shortcuts/commands/sudoers
    python uninstall.py --json          # machine-readable plan

Stdlib-only. Exit code 0 = success/dry-run, 1 = something failed.
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# ── Artifact catalogue ──────────────────────────────────────────────────────

# (absolute path, description) — require root to remove.
SYSTEM_ARTIFACTS = [
    ("/usr/local/bin/jarvis", "Global 'jarvis' command"),
    ("/usr/local/bin/jarvis-app", "Desktop app wrapper"),
    ("/usr/share/applications/jarvis.desktop", "App menu entry"),
    ("/usr/share/icons/hicolor/256x256/apps/jarvis.png", "App icon"),
    ("/etc/sudoers.d/jarvis", "Passwordless sudo rules"),
]

# (relative to home, description) — user-level integrations.
HOME_INTEGRATIONS = [
    (".config/autostart/jarvis.desktop", "Login autostart entry"),
    ("Desktop/Jarvis.desktop", "Desktop shortcut"),
    ("Desktop/JARVIS.desktop", "Desktop shortcut (app)"),
]

# (relative to home, description) — user data JARVIS created.
HOME_DATA = [
    ("jarvis_captures", "Captures directory (wifi/osint/etc.)"),
    ("JarvisProjects", "Generated projects directory"),
]

# (relative to repo, description) — secrets + personal data. Kept by --keep-data.
DATA_ARTIFACTS = [
    ("config/api_keys.json", "API keys"),
    ("config/email_config.json", "Email credentials"),
    ("config/telegram_config.json", "Telegram config"),
    ("config/notion_config.json", "Notion token"),
    ("config/scope.json", "Pentest scope / RoE"),
    ("config/google_client_secret.json", "Google OAuth client secret"),
    ("config/.credentials", "Encrypted credential vault + OAuth tokens"),
    ("config/telegram_sessions", "Telegram sessions"),
    ("memory", "Long-term memory, notes and findings databases"),
    ("reports", "Generated pentest reports"),
    ("browser_profiles", "Browser session profiles"),
]

# (relative to repo, description) — caches / logs / virtualenv. Always removed.
RUNTIME_ARTIFACTS = [
    ("venv", "Python virtualenv"),
    (".venv", "Python virtualenv"),
    ("logs", "Runtime logs"),
    ("kali_agent_logs", "Kali agent logs"),
    ("kali_agent_scripts", "Generated Kali scripts"),
    ("telegram-terabox-backup", "Telegram backup cache"),
    (".pytest_cache", "pytest cache"),
    ("config/dependencies.json", "Dependency registry"),
]

CATEGORY_LABELS = {
    "system": " System integrations (need root)",
    "integration": "🖥️  Desktop / autostart integrations",
    "data": "🔑 Secrets & personal data",
    "runtime": "🧹 Caches, logs & virtualenv",
}


def _detect_home() -> Path:
    """Real user's home even when running under sudo."""
    sudo_user = os.environ.get("SUDO_USER", "")
    if sudo_user and sudo_user != "root":
        try:
            import pwd
            return Path(pwd.getpwnam(sudo_user).pw_dir)
        except Exception:
            pass
    return Path.home()


def _is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _entry(path: Path, category: str, description: str) -> dict:
    try:
        exists = path.exists() or path.is_symlink()
        is_dir = path.is_dir() and not path.is_symlink()
    except OSError:
        # Can't stat the path (e.g. a root-only dir like /etc/sudoers.d when
        # we're not root). Assume it may exist and needs root; removal is
        # gated by the needs_root check anyway, so this is safe.
        exists = True
        is_dir = False
    return {
        "path": str(path),
        "category": category,
        "description": description,
        "exists": exists,
        "is_dir": is_dir,
        "needs_root": category == "system",
    }


def _pycache_dirs(base_dir: Path):
    skip_parts = {".git", "venv", ".venv", "node_modules"}
    for p in base_dir.rglob("__pycache__"):
        if any(part in skip_parts for part in p.parts):
            continue
        yield p


def build_plan(base_dir=None, home_dir=None, keep_data=False,
               integrations_only=False, system_paths=None):
    base = Path(base_dir) if base_dir else BASE_DIR
    home = Path(home_dir) if home_dir else _detect_home()
    plan = []

    # System integrations
    sys_list = system_paths if system_paths is not None else SYSTEM_ARTIFACTS
    for path, desc in sys_list:
        plan.append(_entry(Path(path), "system", desc))

    # User-level integrations
    for rel, desc in HOME_INTEGRATIONS:
        plan.append(_entry(home / rel, "integration", desc))

    if not integrations_only:
        if not keep_data:
            for rel, desc in HOME_DATA:
                plan.append(_entry(home / rel, "data", desc))
            for rel, desc in DATA_ARTIFACTS:
                plan.append(_entry(base / rel, "data", desc))
        for rel, desc in RUNTIME_ARTIFACTS:
            plan.append(_entry(base / rel, "runtime", desc))
        for p in _pycache_dirs(base):
            plan.append(_entry(p, "runtime", "Python bytecode cache"))

    return plan


def remove_plan(plan, dry_run=False):
    """Remove existing artifacts. Returns a list of result dicts."""
    results = []
    root = _is_root()
    for item in plan:
        if not item["exists"]:
            results.append({**item, "action": "absent"})
            continue
        if item["needs_root"] and not root:
            results.append({**item, "action": "needs_root"})
            continue
        if dry_run:
            results.append({**item, "action": "would_remove"})
            continue
        p = Path(item["path"])
        try:
            if p.is_symlink() or p.is_file():
                p.unlink()
            elif p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink(missing_ok=True)
            results.append({**item, "action": "removed"})
        except Exception as e:
            results.append({**item, "action": "failed", "error": str(e)})
    return results


def _print_plan(plan):
    present = [i for i in plan if i["exists"]]
    print("🗑️  VINCEVISION / JARVIS uninstall plan\n" + "─" * 50)
    if not present:
        print("Nothing found to remove — looks already clean.")
        return
    for cat, label in CATEGORY_LABELS.items():
        items = [i for i in present if i["category"] == cat]
        if not items:
            continue
        print(f"\n{label}")
        for i in items:
            kind = "dir " if i["is_dir"] else "file"
            root_tag = "  [root]" if i["needs_root"] else ""
            print(f"  • {kind}  {i['path']}{root_tag}")
            print(f"         {i['description']}")
    print("\n" + "─" * 50)
    print(f"{len(present)} item(s) would be removed.")
    print("📁 The repository source code and .git are NOT touched.")


def _sudo_hint(results):
    paths = [r["path"] for r in results if r["action"] == "needs_root"]
    if paths:
        print("\n🔐 Some system files need root. Run:")
        print("   sudo rm -f " + " ".join(paths))


def _confirm() -> bool:
    try:
        answer = input("\nType 'yes' to confirm uninstall: ").strip().lower()
    except EOFError:
        return False
    return answer in ("yes", "y", "uninstall")


def main(argv=None):
    parser = argparse.ArgumentParser(description="JARVIS safe uninstaller")
    parser.add_argument("--dry-run", action="store_true", help="show plan, delete nothing")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    parser.add_argument("--keep-data", action="store_true",
                        help="preserve secrets, memory, reports and browser sessions")
    parser.add_argument("--integrations-only", action="store_true",
                        help="only remove shortcuts/commands/sudoers, keep everything else")
    parser.add_argument("--json", action="store_true", help="machine-readable plan")
    parser.add_argument("--base-dir", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--home-dir", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    plan = build_plan(base_dir=args.base_dir, home_dir=args.home_dir,
                      keep_data=args.keep_data, integrations_only=args.integrations_only)

    if args.json:
        print(json.dumps(plan, indent=2))
        return 0

    _print_plan(plan)

    if args.dry_run:
        print("\n(dry-run — nothing was deleted)")
        return 0

    if not args.yes:
        if not sys.stdin.isatty():
            print("\nNon-interactive shell: nothing deleted. Re-run with --yes to proceed.")
            return 0
        if not _confirm():
            print("Cancelled — nothing was deleted.")
            return 0

    results = remove_plan(plan, dry_run=False)
    removed = [r for r in results if r["action"] == "removed"]
    failed = [r for r in results if r["action"] == "failed"]

    print(f"\n✅ Removed {len(removed)} item(s).")
    for r in failed:
        print(f"❌ Failed: {r['path']} — {r.get('error', '')}")
    _sudo_hint(results)

    print("\n📁 To also remove the source code itself (optional):")
    base = Path(args.base_dir) if args.base_dir else BASE_DIR
    print(f"   rm -rf {base}")
    print("\n👋 JARVIS uninstalled. Thanks for flying with us.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
