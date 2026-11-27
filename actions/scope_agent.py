"""
scope_agent.py — VINCEVISION Rules-of-Engagement / authorization scope
──────────────────────────────────────────────────────────────────────
Professional pentests run ONLY against explicitly authorized targets. This
module manages that scope and provides a fail-closed authorization check
(`is_authorized`) that other tooling can call before touching a target.

Scope is stored in ``config/scope.json`` (gitignored — client target lists
are sensitive). Nothing here performs attacks; it only records and checks
authorization.

Actions: add / remove / list / check / authorize / help
"""

import ipaddress
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


SCOPE_PATH = _base_dir() / "config" / "scope.json"


def _load() -> dict:
    try:
        if SCOPE_PATH.exists():
            with open(SCOPE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                data.setdefault("targets", [])
                return data
    except Exception as e:
        print(f"[Scope] ⚠️ load failed: {e}")
    return {"targets": [], "authorized_by": "", "notes": ""}


def _save(scope: dict) -> None:
    SCOPE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SCOPE_PATH, "w", encoding="utf-8") as f:
        json.dump(scope, f, indent=2)


def host_from_target(target: str) -> str:
    """Extract a bare hostname/IP from a URL, host:port, or path-ish string."""
    t = (target or "").strip()
    if not t:
        return ""
    if "://" in t:
        t = urlparse(t).hostname or t
    else:
        t = t.split("/", 1)[0]
        if t.count(":") == 1:           # host:port (not IPv6)
            t = t.split(":", 1)[0]
        t = t.strip("[]")
    return t.lower().rstrip(".")


def is_authorized(target: str, scope: dict | None = None) -> bool:
    """Fail-closed: True only if target matches an explicit scope entry."""
    scope = scope if scope is not None else _load()
    host = host_from_target(target)
    if not host:
        return False
    entries = [e["target"] if isinstance(e, dict) else str(e)
               for e in scope.get("targets", [])]

    # IP / CIDR matching
    try:
        ip = ipaddress.ip_address(host)
        for e in entries:
            try:
                if ip in ipaddress.ip_network(e, strict=False):
                    return True
            except ValueError:
                continue
        return False
    except ValueError:
        pass

    # Domain matching (exact or subdomain)
    for e in entries:
        e = str(e).lower().rstrip(".")
        if host == e or host.endswith("." + e):
            return True
    return False


def add_target(target: str, note: str = "") -> str:
    host = host_from_target(target)
    if not host:
        return "Provide a valid target (IP, CIDR, or domain), sir."
    scope = _load()
    for e in scope["targets"]:
        existing = e["target"] if isinstance(e, dict) else e
        if existing.lower() == host:
            return f"{host} is already in scope."
    scope["targets"].append({"target": host, "note": note})
    _save(scope)
    return f"✅ Added {host} to authorized scope."


def remove_target(target: str) -> bool:
    host = host_from_target(target)
    scope = _load()
    before = len(scope["targets"])
    scope["targets"] = [
        e for e in scope["targets"]
        if (e["target"] if isinstance(e, dict) else e).lower() != host
    ]
    _save(scope)
    return len(scope["targets"]) < before


def list_targets() -> list:
    return _load().get("targets", [])


def set_authorization(authorized_by: str, notes: str = "") -> None:
    scope = _load()
    scope["authorized_by"] = authorized_by
    if notes:
        scope["notes"] = notes
    _save(scope)


def scope_agent(parameters: dict, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "list")).lower().strip()

    if action in ("help", "setup"):
        return ("Rules of Engagement: add authorized targets before testing. "
                "Actions: add, remove, list, check, authorize. "
                "Example: 'scope add 192.168.1.0/24' or 'scope add example.com'.")

    if action == "add":
        target = (params.get("target") or params.get("host") or "").strip()
        return add_target(target, params.get("note", ""))

    if action == "remove":
        target = (params.get("target") or params.get("host") or "").strip()
        return (f"✅ Removed {host_from_target(target)} from scope."
                if remove_target(target) else "That target wasn't in scope, sir.")

    if action == "list":
        scope = _load()
        targets = scope.get("targets", [])
        if not targets and not scope.get("authorized_by"):
            return "No authorized targets in scope yet, sir."
        lines = ["🎯 AUTHORIZED SCOPE"]
        if scope.get("authorized_by"):
            lines.append(f"  Authorized by: {scope['authorized_by']}")
        if targets:
            for e in targets:
                t = e["target"] if isinstance(e, dict) else e
                note = e.get("note", "") if isinstance(e, dict) else ""
                lines.append(f"  • {t}" + (f"  ({note})" if note else ""))
        else:
            lines.append("  (no targets added yet)")
        return "\n".join(lines)

    if action == "check":
        target = (params.get("target") or params.get("host") or "").strip()
        ok = is_authorized(target)
        if speak:
            speak("Target is in scope, sir." if ok else "Target is NOT authorized, sir.")
        return (f"✅ {host_from_target(target)} IS authorized." if ok
                else f"⛔ {host_from_target(target)} is NOT in scope. Do not test it.")

    if action == "authorize":
        by = (params.get("authorized_by") or params.get("by") or "").strip()
        if not by:
            return "Who authorized this engagement, sir? Provide authorized_by."
        set_authorization(by, params.get("notes", ""))
        return f"✅ Engagement authorization recorded: {by}."

    return "❌ Unknown scope action. Try: add, remove, list, check, authorize."
