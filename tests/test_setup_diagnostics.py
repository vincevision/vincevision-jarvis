"""Offline tests for clone-and-run diagnostics.

Covers the three problems a real `pip install -r requirements.txt` +
`playwright install chromium` run exposed:

  1. a failed browser download was reported as ✅ (non-empty cache != browser)
  2. an invalid escape sequence emitted SyntaxWarning on Python 3.12+
  3. the unused legacy google-generativeai SDK made pip backtrack for minutes

Nothing here downloads, launches a browser, or touches the network.
"""

import ast
import os
import sys
import warnings
from pathlib import Path

import pytest

from core import browser_check as bc

ROOT = Path(__file__).resolve().parent.parent


# ── fixtures: fake playwright caches ───────────────────────────────────────

@pytest.fixture
def empty_cache(tmp_path):
    d = tmp_path / ".cache" / "ms-playwright"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def stale_cache(tmp_path):
    """A failed download: folder exists, holds junk, no Chromium binary."""
    d = tmp_path / ".cache" / "ms-playwright"
    (d / ".links").mkdir(parents=True)
    (d / "chromium-1255").mkdir()
    (d / "chromium-1255" / "partial.zip").write_bytes(b"truncated")
    return d


@pytest.fixture
def good_cache(tmp_path):
    d = tmp_path / ".cache" / "ms-playwright"
    exe = d / "chromium-1255" / "chrome-linux64" / "chrome"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    return d


@pytest.fixture
def legacy_cache(tmp_path):
    d = tmp_path / ".cache" / "ms-playwright"
    exe = d / "chromium-1100" / "chrome-linux" / "chrome"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    return d


# ── find_chromium ──────────────────────────────────────────────────────────

def test_finds_modern_layout(good_cache):
    exe = bc.find_chromium(good_cache)
    assert exe is not None and exe.name == "chrome"


def test_finds_legacy_layout(legacy_cache):
    assert bc.find_chromium(legacy_cache) is not None


def test_empty_cache_has_no_chromium(empty_cache):
    assert bc.find_chromium(empty_cache) is None


def test_stale_cache_has_no_chromium(stale_cache):
    assert bc.find_chromium(stale_cache) is None


def test_missing_cache_has_no_chromium(tmp_path):
    assert bc.find_chromium(tmp_path / "nope") is None


def test_directory_named_chrome_is_not_an_executable(tmp_path):
    fake = tmp_path / "chromium-1" / "chrome-linux" / "chrome"
    fake.mkdir(parents=True)
    assert bc.find_chromium(tmp_path) is None


def test_windows_layout(tmp_path):
    exe = tmp_path / "chromium-1255" / "chrome-win" / "chrome.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("MZ", encoding="utf-8")
    assert bc.find_chromium(tmp_path) == exe


def test_mac_layout(tmp_path):
    exe = (tmp_path / "chromium-1255" / "chrome-mac" / "Chromium.app"
           / "Contents" / "MacOS" / "Chromium")
    exe.parent.mkdir(parents=True)
    exe.write_text("bin", encoding="utf-8")
    assert bc.find_chromium(tmp_path) == exe


def test_headless_shell_found(tmp_path):
    exe = (tmp_path / "chromium_headless_shell-1255"
           / "chrome-headless-shell-linux64" / "chrome-headless-shell")
    exe.parent.mkdir(parents=True)
    exe.write_text("bin", encoding="utf-8")
    assert bc.find_headless_shell(tmp_path) == exe


def test_headless_shell_is_not_full_chromium(tmp_path):
    exe = (tmp_path / "chromium_headless_shell-1255"
           / "chrome-headless-shell-linux64" / "chrome-headless-shell")
    exe.parent.mkdir(parents=True)
    exe.write_text("bin", encoding="utf-8")
    assert bc.find_chromium(tmp_path) is None


def test_find_chromium_never_raises_on_file_path(tmp_path):
    f = tmp_path / "afile"
    f.write_text("x", encoding="utf-8")
    assert bc.find_chromium(f) is None


# ── cache_has_content: the OLD weak check ──────────────────────────────────

def test_stale_cache_passes_the_old_weak_check(stale_cache):
    # This is exactly why the old check produced a false ✅.
    assert bc.cache_has_content(stale_cache) is True
    assert bc.find_chromium(stale_cache) is None


def test_empty_cache_fails_weak_check(empty_cache):
    assert bc.cache_has_content(empty_cache) is False


# ── chromium_status ────────────────────────────────────────────────────────

def test_status_installed(good_cache):
    st = bc.chromium_status(good_cache)
    assert st["installed"] is True and st["stale_cache"] is False
    assert st["executable"].endswith("chrome")


def test_status_stale(stale_cache):
    st = bc.chromium_status(stale_cache)
    assert st["installed"] is False and st["stale_cache"] is True


def test_status_absent(empty_cache):
    st = bc.chromium_status(empty_cache)
    assert st["installed"] is False and st["stale_cache"] is False


def test_status_always_has_hint(good_cache):
    assert "playwright install" in bc.chromium_status(good_cache)["hint"]


def test_status_missing_cache_dir(tmp_path):
    st = bc.chromium_status(tmp_path / "nope")
    assert st["installed"] is False and st["cache"] == ""


def test_describe_installed(good_cache):
    assert "ready" in bc.describe(bc.chromium_status(good_cache))


def test_describe_stale(stale_cache):
    assert "did not complete" in bc.describe(bc.chromium_status(stale_cache))


def test_describe_absent(empty_cache):
    assert "not installed" in bc.describe(bc.chromium_status(empty_cache))


# ── install command ────────────────────────────────────────────────────────

def test_install_command_uses_module_form():
    cmd = bc.install_command()
    assert cmd[1:4] == ["-m", "playwright", "install"]
    assert cmd[-1] == "chromium"


def test_install_command_uses_this_interpreter():
    assert bc.install_command()[0] == (sys.executable or "python")


def test_install_command_with_deps():
    assert "--with-deps" in bc.install_command(with_deps=True)


def test_install_hint_is_copy_pastable():
    hint = bc.install_hint()
    assert hint.startswith("python -m playwright install")
    assert sys.executable not in hint      # no sandbox-specific absolute path


def test_cache_candidates_respects_env(monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "custom"))
    assert bc.cache_candidates()[0] == tmp_path / "custom"


def test_cache_candidates_ignores_zero(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "0")
    assert all(str(p) != "0" for p in bc.cache_candidates())


def test_cache_candidates_dedupes(monkeypatch, tmp_path):
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    paths = [str(p) for p in bc.cache_candidates(tmp_path)]
    assert len(paths) == len(set(paths))


# ── doctor.check_browser ───────────────────────────────────────────────────

def test_doctor_browser_ok(good_cache):
    import doctor
    chk = doctor.check_browser(bc.chromium_status(good_cache))
    assert chk["status"] == "ok"


def test_doctor_browser_warns_when_stale(stale_cache):
    import doctor
    chk = doctor.check_browser(bc.chromium_status(stale_cache))
    assert chk["status"] == "warn"
    assert "did not complete" in chk["detail"]
    assert "playwright install" in chk["fix"]


def test_doctor_browser_warns_when_absent(empty_cache):
    import doctor
    chk = doctor.check_browser(bc.chromium_status(empty_cache))
    assert chk["status"] == "warn" and "not installed" in chk["detail"]


def test_doctor_browser_mentions_with_deps(stale_cache):
    import doctor
    assert "--with-deps" in doctor.check_browser(bc.chromium_status(stale_cache))["fix"]


def test_doctor_browser_survives_broken_module(monkeypatch):
    import doctor
    monkeypatch.setitem(sys.modules, "core.browser_check", None)
    chk = doctor.check_browser()
    assert chk["status"] == "warn"


def test_doctor_run_all_includes_browser():
    import doctor
    names = [c["name"] for c in doctor.run_all()]
    assert "browser:chromium" in names


# ── env_setup honesty ──────────────────────────────────────────────────────

def test_env_setup_does_not_accept_stale_cache(monkeypatch, stale_cache, capsys):
    from core import env_setup
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setattr(env_setup, "_get_real_user", lambda: "tester")
    monkeypatch.setattr(env_setup.Path, "home", classmethod(lambda cls: stale_cache.parent.parent))
    monkeypatch.setattr(env_setup.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("no network")))
    env_setup.fix_playwright()
    out = capsys.readouterr().out
    assert "no Chromium" in out or "download incomplete" in out
    assert "Playwright ✅" not in out


def test_env_setup_accepts_real_binary(monkeypatch, good_cache, capsys):
    from core import env_setup
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setattr(env_setup, "_get_real_user", lambda: "tester")
    monkeypatch.setattr(env_setup.Path, "home", classmethod(lambda cls: good_cache.parent.parent))
    env_setup.fix_playwright()
    out = capsys.readouterr().out
    assert "Playwright ✅" in out
    assert os.environ.get("PLAYWRIGHT_BROWSERS_PATH") == str(good_cache)


def test_env_setup_install_uses_module_form(monkeypatch, empty_cache):
    from core import env_setup
    calls = []
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setattr(env_setup, "_get_real_user", lambda: "tester")
    monkeypatch.setattr(env_setup.Path, "home", classmethod(lambda cls: empty_cache.parent.parent))

    def fake_run(cmd, **kw):
        calls.append(cmd)
        raise OSError("download blocked")
    monkeypatch.setattr(env_setup.subprocess, "run", fake_run)
    env_setup.fix_playwright()
    assert calls and calls[0][1:4] == ["-m", "playwright", "install"]


def test_env_setup_respects_preset_env(monkeypatch, capsys):
    from core import env_setup
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/preset/path")
    env_setup.fix_playwright()
    assert "already set" in capsys.readouterr().out


# ── repo hygiene regressions ───────────────────────────────────────────────

def _repo_py_files():
    for p in sorted(ROOT.rglob("*.py")):
        if any(x in p.parts for x in ("venv", ".git", "__pycache__", "node_modules")):
            continue
        yield p


def test_no_invalid_escape_sequences_anywhere():
    """Invalid escapes are SyntaxWarning on 3.12+ and become errors later."""
    offenders = []
    for p in _repo_py_files():
        src = p.read_text(encoding="utf-8", errors="replace")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                compile(src, str(p), "exec")
            except SyntaxError as exc:
                offenders.append(f"{p.relative_to(ROOT)}:{exc.lineno} {exc.msg}")
                continue
            for w in caught:
                if "escape" in str(w.message):
                    offenders.append(f"{p.relative_to(ROOT)}:{w.lineno} {w.message}")
    assert offenders == [], "invalid escape sequences:\n" + "\n".join(offenders)


def test_legacy_generativeai_not_required():
    """It is unused and forces pip to backtrack/downgrade google-api-core."""
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    active = [ln.strip() for ln in text.splitlines()
              if ln.strip() and not ln.strip().startswith("#")]
    assert not any(ln.lower().startswith("google-generativeai") for ln in active)


def test_no_module_imports_legacy_generativeai():
    for p in _repo_py_files():
        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert not any(n.startswith("google.generativeai") for n in names), \
                f"{p.relative_to(ROOT)} imports the removed legacy SDK"


def test_modern_genai_still_required():
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "\ngoogle-genai\n" in text


def test_every_module_compiles():
    for p in _repo_py_files():
        compile(p.read_text(encoding="utf-8", errors="replace"), str(p), "exec")

