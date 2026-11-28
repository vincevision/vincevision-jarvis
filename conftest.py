"""Pytest bootstrap.

1. Make the repo root importable when running pytest from any cwd.
2. Keep the suite hermetic: the crash net must never write into the real
   repository's logs/ while tests exercise failure paths.
"""
import sys
from pathlib import Path

import pytest

ROOT = str(Path(__file__).resolve().parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture(autouse=True)
def _isolate_runtime_state(tmp_path, monkeypatch):
    """Redirect crash-log and alert-delivery state into a per-test sandbox.

    Without this, tests that deliberately raise inside a @safe_tool — or that
    trigger a price-watch alert — would append to the developer's real
    logs/crashes.log, logs/alerts.log and memory/alerts.json.
    """
    sandbox = tmp_path / "_runtime"
    sandbox.mkdir(exist_ok=True)
    try:
        from core import safe_run
        monkeypatch.setattr(safe_run, "_base_dir", lambda: sandbox)
        monkeypatch.setattr(safe_run, "CRASH_LOG", Path("logs") / "crashes.log")
    except Exception:
        pass
    try:
        from core import alerts
        monkeypatch.setattr(alerts, "CONFIG_PATH", sandbox / "alerts.json")
        monkeypatch.setattr(alerts, "HISTORY_PATH", sandbox / "alert_history.json")
        monkeypatch.setattr(alerts, "LOG_PATH", sandbox / "alerts.log")
    except Exception:
        pass
    yield
