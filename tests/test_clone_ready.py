"""Clone-readiness tests: doctor.py, config templates, and no personal paths.

These run offline with stdlib + pytest only (matching CI). They verify that a
fresh clone has a working setup checker, valid templates, and no hardcoded
personal usernames/paths left in the shipped code.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

import doctor

ROOT = Path(__file__).resolve().parent.parent


# ── doctor: pure check functions ────────────────────────────────────────────

def test_check_python_ok():
    c = doctor.check_python()
    assert c["status"] in ("ok", "warn")  # never fail on the CI interpreter


def test_check_assets_present():
    checks = doctor.check_assets(ROOT)
    assert all(c["status"] == "ok" for c in checks), checks


def test_check_dirs(tmp_path):
    checks = doctor.check_dirs(tmp_path)
    assert all(c["status"] == "warn" for c in checks)
    (tmp_path / "config").mkdir()
    checks = doctor.check_dirs(tmp_path)
    assert any(c["name"] == "dir:config" and c["status"] == "ok" for c in checks)


def test_api_keys_missing(tmp_path):
    c = doctor.check_api_keys(tmp_path)
    assert c["status"] == "fail"
    assert "--fix" in c["fix"]


def test_api_keys_placeholder(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "api_keys.json").write_text(
        json.dumps({"gemini_api_key": "YOUR_GEMINI_API_KEY_HERE"}))
    c = doctor.check_api_keys(tmp_path)
    assert c["status"] == "fail"


def test_api_keys_gemini_only_warns(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "api_keys.json").write_text(
        json.dumps({"gemini_api_key": "real-key-abc123"}))
    c = doctor.check_api_keys(tmp_path)
    assert c["status"] == "warn"  # groq missing


def test_api_keys_both_ok(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "api_keys.json").write_text(
        json.dumps({"gemini_api_key": "real-key-abc123", "groq_api_key": "real-groq-xyz"}))
    c = doctor.check_api_keys(tmp_path)
    assert c["status"] == "ok"


def test_api_keys_invalid_json(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "api_keys.json").write_text("{not json")
    c = doctor.check_api_keys(tmp_path)
    assert c["status"] == "fail"


def test_is_placeholder():
    assert doctor._is_placeholder("")
    assert doctor._is_placeholder("YOUR_KEY_HERE")
    assert doctor._is_placeholder(None)
    assert not doctor._is_placeholder("real-key-123")


def test_check_dependencies_injected_finder():
    # finder that "finds" only requests
    checks = doctor.check_dependencies(finder=lambda name: object() if name == "requests" else None)
    by_name = {c["name"]: c for c in checks}
    assert by_name["dep:requests"]["status"] == "ok"
    assert by_name["dep:google-genai"]["status"] == "fail"  # essential
    assert by_name["dep:psutil"]["status"] == "warn"        # optional


def test_check_dependencies_finder_raises():
    def boom(name):
        raise ImportError("nope")
    checks = doctor.check_dependencies(finder=boom)
    assert all(c["status"] in ("fail", "warn") for c in checks)


# ── doctor: fixes + run_all ─────────────────────────────────────────────────

def test_apply_fixes_creates_dirs_and_templates(tmp_path):
    # seed templates like a fresh clone
    (tmp_path / "config").mkdir()
    for template in doctor.TEMPLATES:
        (tmp_path / "config" / template).write_text("{}")
    actions = doctor.apply_fixes(tmp_path)
    assert any("created config/api_keys.json" in a for a in actions)
    for d in doctor.RUNTIME_DIRS:
        assert (tmp_path / d).is_dir()
    for real in doctor.TEMPLATES.values():
        assert (tmp_path / "config" / real).exists()


def test_apply_fixes_idempotent(tmp_path):
    (tmp_path / "config").mkdir()
    for template in doctor.TEMPLATES:
        (tmp_path / "config" / template).write_text("{}")
    doctor.apply_fixes(tmp_path)
    actions = doctor.apply_fixes(tmp_path)
    assert actions == []  # nothing left to do


def test_apply_fixes_does_not_overwrite(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "api_keys.example.json").write_text("{}")
    (tmp_path / "config" / "api_keys.json").write_text('{"gemini_api_key": "keep-me"}')
    doctor.apply_fixes(tmp_path)
    assert "keep-me" in (tmp_path / "config" / "api_keys.json").read_text()


def test_run_all_returns_checks(tmp_path):
    checks = doctor.run_all(base_dir=tmp_path, finder=lambda name: None)
    assert isinstance(checks, list) and checks
    assert all({"name", "status", "detail"} <= set(c) for c in checks)


def test_run_all_json_serializable(tmp_path):
    checks = doctor.run_all(base_dir=tmp_path, finder=lambda name: None)
    json.dumps(checks)  # must not raise


# ── doctor: CLI ─────────────────────────────────────────────────────────────

def test_doctor_cli_json_runs():
    proc = subprocess.run([sys.executable, str(ROOT / "doctor.py"), "--json"],
                          capture_output=True, text=True, timeout=60)
    # exit code may be 0 or 1 depending on env; output must be valid JSON
    data = json.loads(proc.stdout)
    assert isinstance(data, list) and data


def test_doctor_cli_help():
    proc = subprocess.run([sys.executable, str(ROOT / "doctor.py"), "--help"],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0
    assert "--fix" in proc.stdout


# ── templates are valid JSON + committed ────────────────────────────────────

@pytest.mark.parametrize("template", list(doctor.TEMPLATES))
def test_template_valid_json(template):
    path = ROOT / "config" / template
    assert path.exists(), f"{template} should be committed"
    json.loads(path.read_text(encoding="utf-8"))


def test_templates_are_gitignored_targets():
    # the real config files must remain gitignored
    gitignore = (ROOT / ".gitignore").read_text()
    for real in ("api_keys.json", "notion_config.json", "telegram_config.json",
                 "email_config.json", "scope.json", "google_client_secret.json"):
        assert f"config/{real}" in gitignore


# ── no hardcoded personal paths in shipped code ─────────────────────────────

def test_no_personal_username_in_code():
    offenders = []
    for py in list((ROOT / "actions").glob("*.py")) + list((ROOT / "core").glob("*.py")) + [ROOT / "main.py"]:
        text = py.read_text(encoding="utf-8", errors="replace")
        if "/home/vincent" in text or 'return "vincent"' in text:
            offenders.append(str(py.relative_to(ROOT)))
    assert not offenders, f"hardcoded personal paths remain: {offenders}"


def test_readme_exists_and_mentions_doctor():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "doctor.py" in readme
    assert "git clone" in readme
    assert "api_keys" in readme
