"""Safety tests for uninstall.py.

Everything runs against tmp_path dirs with injected system paths — no real
system file, home dir, or repo file is ever touched. The core guarantees we
verify: dry-run deletes nothing, --keep-data preserves secrets, the repo
source and .git are never in the plan, and root-only files are skipped when
not root.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

import uninstall

ROOT = Path(__file__).resolve().parent.parent


def _seed(base: Path, home: Path):
    """Create a realistic set of artifacts in tmp dirs."""
    # repo data + runtime
    (base / "config").mkdir(parents=True)
    (base / "config" / "api_keys.json").write_text('{"gemini_api_key": "x"}')
    (base / "config" / ".credentials").mkdir()
    (base / "config" / ".credentials" / "vault.json").write_text("{}")
    (base / "memory").mkdir()
    (base / "memory" / "long_term.db").write_text("db")
    (base / "reports").mkdir()
    (base / "reports" / "r.md").write_text("# report")
    (base / "logs").mkdir()
    (base / "logs" / "a.log").write_text("log")
    (base / "__pycache__").mkdir()
    (base / "__pycache__" / "x.pyc").write_text("bytecode")
    # source that must NEVER be removed
    (base / "main.py").write_text("# source")
    (base / ".git").mkdir()
    (base / ".git" / "HEAD").write_text("ref")
    # home artifacts
    (home / ".config" / "autostart").mkdir(parents=True)
    (home / ".config" / "autostart" / "jarvis.desktop").write_text("[Desktop Entry]")
    (home / "Desktop").mkdir()
    (home / "Desktop" / "Jarvis.desktop").write_text("[Desktop Entry]")
    (home / "jarvis_captures").mkdir()
    (home / "JarvisProjects").mkdir()


# ── build_plan ──────────────────────────────────────────────────────────────

def test_plan_never_includes_source_or_git(tmp_path):
    base, home = tmp_path / "repo", tmp_path / "home"
    _seed(base, home)
    plan = uninstall.build_plan(base_dir=base, home_dir=home, system_paths=[])
    paths = {i["path"] for i in plan}
    assert str(base / "main.py") not in paths
    assert not any(p.startswith(str(base / ".git")) for p in paths)
    assert str(base) not in paths  # never the repo root itself


def test_plan_finds_data_and_runtime(tmp_path):
    base, home = tmp_path / "repo", tmp_path / "home"
    _seed(base, home)
    plan = uninstall.build_plan(base_dir=base, home_dir=home, system_paths=[])
    present = {i["path"] for i in plan if i["exists"]}
    assert str(base / "config" / "api_keys.json") in present
    assert str(base / "memory") in present
    assert str(base / "logs") in present
    assert str(home / "jarvis_captures") in present
    assert str(home / ".config" / "autostart" / "jarvis.desktop") in present


def test_keep_data_excludes_secrets(tmp_path):
    base, home = tmp_path / "repo", tmp_path / "home"
    _seed(base, home)
    plan = uninstall.build_plan(base_dir=base, home_dir=home, keep_data=True, system_paths=[])
    cats = {i["category"] for i in plan}
    assert "data" not in cats
    paths = {i["path"] for i in plan}
    assert str(base / "config" / "api_keys.json") not in paths
    assert str(base / "memory") not in paths
    # runtime still present
    assert str(base / "logs") in paths


def test_integrations_only(tmp_path):
    base, home = tmp_path / "repo", tmp_path / "home"
    _seed(base, home)
    plan = uninstall.build_plan(base_dir=base, home_dir=home,
                                integrations_only=True, system_paths=[])
    cats = {i["category"] for i in plan}
    assert cats <= {"system", "integration"}
    paths = {i["path"] for i in plan}
    assert str(base / "memory") not in paths
    assert str(base / "logs") not in paths


@pytest.mark.skipif(uninstall._is_root(), reason="root bypasses permission checks")
def test_entry_handles_permission_denied(tmp_path):
    # Regression: on real Linux, /etc/sudoers.d is root-only (mode 750) and
    # Path.exists() raises PermissionError. _entry must not crash.
    locked = tmp_path / "sudoers.d"
    locked.mkdir()
    locked.chmod(0o000)
    try:
        item = uninstall._entry(locked / "jarvis", "system", "sudoers rules")
        assert item["exists"] is True       # assumed present, needs root
        assert item["needs_root"] is True
        assert item["is_dir"] is False
    finally:
        locked.chmod(0o755)  # let pytest clean up tmp_path


@pytest.mark.skipif(uninstall._is_root(), reason="root bypasses permission checks")
def test_build_plan_survives_inaccessible_system_path(tmp_path):
    base, home = tmp_path / "repo", tmp_path / "home"
    _seed(base, home)
    locked = tmp_path / "sudoers.d"
    locked.mkdir()
    locked.chmod(0o000)
    try:
        plan = uninstall.build_plan(
            base_dir=base, home_dir=home,
            system_paths=[(str(locked / "jarvis"), "sudoers rules")])
        assert any(i["category"] == "system" for i in plan)
    finally:
        locked.chmod(0o755)


def test_system_entries_flagged_needs_root(tmp_path):
    base, home = tmp_path / "repo", tmp_path / "home"
    _seed(base, home)
    fake_sys = [(str(tmp_path / "jarvis"), "Global command")]
    (tmp_path / "jarvis").write_text("#!/bin/bash")
    plan = uninstall.build_plan(base_dir=base, home_dir=home, system_paths=fake_sys)
    sys_items = [i for i in plan if i["category"] == "system"]
    assert sys_items and all(i["needs_root"] for i in sys_items)


# ── remove_plan ─────────────────────────────────────────────────────────────

def test_dry_run_deletes_nothing(tmp_path):
    base, home = tmp_path / "repo", tmp_path / "home"
    _seed(base, home)
    plan = uninstall.build_plan(base_dir=base, home_dir=home, system_paths=[])
    results = uninstall.remove_plan(plan, dry_run=True)
    assert all(r["action"] in ("would_remove", "absent", "needs_root") for r in results)
    # everything still on disk
    assert (base / "config" / "api_keys.json").exists()
    assert (base / "memory").exists()
    assert (home / "jarvis_captures").exists()


def test_remove_deletes_files_and_dirs(tmp_path):
    base, home = tmp_path / "repo", tmp_path / "home"
    _seed(base, home)
    plan = uninstall.build_plan(base_dir=base, home_dir=home, system_paths=[])
    results = uninstall.remove_plan(plan, dry_run=False)
    assert any(r["action"] == "removed" for r in results)
    assert not (base / "config" / "api_keys.json").exists()
    assert not (base / "memory").exists()
    assert not (base / "config" / ".credentials").exists()
    assert not (home / "jarvis_captures").exists()
    # source survives
    assert (base / "main.py").exists()
    assert (base / ".git" / "HEAD").exists()


def test_remove_skips_root_when_not_root(tmp_path, monkeypatch):
    base, home = tmp_path / "repo", tmp_path / "home"
    _seed(base, home)
    fake_sys_file = tmp_path / "jarvis"
    fake_sys_file.write_text("#!/bin/bash")
    monkeypatch.setattr(uninstall, "_is_root", lambda: False)
    plan = uninstall.build_plan(base_dir=base, home_dir=home,
                                system_paths=[(str(fake_sys_file), "cmd")])
    results = uninstall.remove_plan(plan, dry_run=False)
    sys_res = [r for r in results if r["category"] == "system"]
    assert sys_res[0]["action"] == "needs_root"
    assert fake_sys_file.exists()  # not deleted without root


def test_remove_root_removes_system(tmp_path, monkeypatch):
    base, home = tmp_path / "repo", tmp_path / "home"
    _seed(base, home)
    fake_sys_file = tmp_path / "jarvis"
    fake_sys_file.write_text("#!/bin/bash")
    monkeypatch.setattr(uninstall, "_is_root", lambda: True)
    plan = uninstall.build_plan(base_dir=base, home_dir=home,
                                system_paths=[(str(fake_sys_file), "cmd")])
    uninstall.remove_plan(plan, dry_run=False)
    assert not fake_sys_file.exists()


def test_keep_data_preserves_secrets_on_remove(tmp_path):
    base, home = tmp_path / "repo", tmp_path / "home"
    _seed(base, home)
    plan = uninstall.build_plan(base_dir=base, home_dir=home, keep_data=True, system_paths=[])
    uninstall.remove_plan(plan, dry_run=False)
    assert (base / "config" / "api_keys.json").exists()
    assert (base / "memory").exists()
    assert (home / "jarvis_captures").exists()
    assert not (base / "logs").exists()  # runtime still cleaned


def test_remove_absent_is_noop(tmp_path):
    base, home = tmp_path / "repo", tmp_path / "home"
    base.mkdir(); home.mkdir()
    plan = uninstall.build_plan(base_dir=base, home_dir=home, system_paths=[])
    results = uninstall.remove_plan(plan, dry_run=False)
    assert all(r["action"] in ("absent", "needs_root") for r in results)


def test_pycache_excludes_git_and_venv(tmp_path):
    base = tmp_path / "repo"
    (base / ".git" / "__pycache__").mkdir(parents=True)
    (base / "venv" / "__pycache__").mkdir(parents=True)
    (base / "actions" / "__pycache__").mkdir(parents=True)
    found = {str(p) for p in uninstall._pycache_dirs(base)}
    assert str(base / "actions" / "__pycache__") in found
    assert not any(".git" in p for p in found)
    assert not any("/venv/" in p for p in found)


# ── CLI ─────────────────────────────────────────────────────────────────────

def test_cli_json_plan(tmp_path):
    base, home = tmp_path / "repo", tmp_path / "home"
    _seed(base, home)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "uninstall.py"), "--json",
         "--base-dir", str(base), "--home-dir", str(home)],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert isinstance(data, list) and data


def test_cli_dry_run_deletes_nothing(tmp_path):
    base, home = tmp_path / "repo", tmp_path / "home"
    _seed(base, home)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "uninstall.py"), "--dry-run",
         "--base-dir", str(base), "--home-dir", str(home)],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0
    assert (base / "config" / "api_keys.json").exists()
    assert (base / "main.py").exists()


def test_cli_noninteractive_without_yes_deletes_nothing(tmp_path):
    base, home = tmp_path / "repo", tmp_path / "home"
    _seed(base, home)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "uninstall.py"),
         "--base-dir", str(base), "--home-dir", str(home)],
        capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    assert proc.returncode == 0
    assert "nothing deleted" in proc.stdout.lower()
    assert (base / "config" / "api_keys.json").exists()


def test_cli_yes_removes_but_keeps_source(tmp_path):
    base, home = tmp_path / "repo", tmp_path / "home"
    _seed(base, home)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "uninstall.py"), "--yes",
         "--base-dir", str(base), "--home-dir", str(home)],
        capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    assert proc.returncode == 0
    assert not (base / "config" / "api_keys.json").exists()
    assert not (base / "memory").exists()
    assert (base / "main.py").exists()
    assert (base / ".git" / "HEAD").exists()


def test_cli_help():
    proc = subprocess.run([sys.executable, str(ROOT / "uninstall.py"), "--help"],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0
    assert "--keep-data" in proc.stdout
    assert "--dry-run" in proc.stdout


# ── Python 3.14 compatibility ──────────────────────────────────────────────
# From 3.14, Path.exists()/is_dir()/is_symlink() return False on EACCES instead
# of raising PermissionError. _entry used to depend on that exception, so on
# 3.14 a root-only artifact (/etc/sudoers.d/jarvis) was reported as ABSENT and
# silently skipped. These tests pin the behaviour on ANY Python version.

def test_probe_permission_denied_is_not_absent(tmp_path, monkeypatch):
    import errno
    target = tmp_path / "locked" / "jarvis"

    def denied(p):
        raise PermissionError(errno.EACCES, "Permission denied", str(p))
    monkeypatch.setattr(uninstall.os, "lstat", denied)
    # Simulate exactly what 3.14's pathlib does.
    monkeypatch.setattr(uninstall.Path, "exists", lambda self, *a, **k: False)
    monkeypatch.setattr(uninstall.Path, "is_dir", lambda self, *a, **k: False)
    monkeypatch.setattr(uninstall.Path, "is_symlink", lambda self, *a, **k: False)
    item = uninstall._entry(target, "system", "sudoers rules")
    assert item["exists"] is True
    assert item["needs_root"] is True
    assert item["is_dir"] is False


def test_probe_missing_is_absent(tmp_path):
    assert uninstall._probe(tmp_path / "nope") == (False, False)


def test_probe_not_a_directory_is_absent(tmp_path):
    f = tmp_path / "file"
    f.write_text("x", encoding="utf-8")
    assert uninstall._probe(f / "child") == (False, False)


def test_probe_existing_file(tmp_path):
    f = tmp_path / "file"
    f.write_text("x", encoding="utf-8")
    assert uninstall._probe(f) == (True, False)


def test_probe_existing_dir(tmp_path):
    d = tmp_path / "dir"
    d.mkdir()
    assert uninstall._probe(d) == (True, True)


def test_probe_symlink_to_dir_is_not_a_dir(tmp_path):
    d = tmp_path / "dir"
    d.mkdir()
    link = tmp_path / "link"
    link.symlink_to(d)
    assert uninstall._probe(link) == (True, False)


def test_probe_broken_symlink_still_exists(tmp_path):
    link = tmp_path / "dangling"
    link.symlink_to(tmp_path / "gone")
    # lstat sees the link itself, so it is present and removable.
    assert uninstall._probe(link) == (True, False)


def test_probe_other_oserror_assumes_present(tmp_path, monkeypatch):
    import errno

    def io_error(p):
        raise OSError(errno.EIO, "I/O error", str(p))
    monkeypatch.setattr(uninstall.os, "lstat", io_error)
    assert uninstall._probe(tmp_path / "x") == (True, False)


def test_probe_null_byte_path_is_absent(tmp_path):
    assert uninstall._probe(str(tmp_path) + "\0bad") == (False, False)


@pytest.mark.skipif(uninstall._is_root(), reason="root bypasses permission checks")
def test_entry_real_locked_dir_reports_present(tmp_path):
    locked = tmp_path / "sudoers.d"
    locked.mkdir()
    locked.chmod(0o000)
    try:
        item = uninstall._entry(locked / "jarvis", "system", "sudoers rules")
        assert item["exists"] is True and item["needs_root"] is True
    finally:
        locked.chmod(0o755)
