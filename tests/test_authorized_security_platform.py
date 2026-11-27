import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_authorized_assessment_requires_scope_and_approval():
    security_agent = importlib.import_module("actions.security_agent")
    result = security_agent.security_agent({
        "action": "authorized_assessment",
        "module": "asset_discovery",
        "target": "10.0.0.0/24",
    })
    assert "authorization" in result.lower() or "approval" in result.lower()
