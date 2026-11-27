"""
Offline tests for the social browser-session backend.

No real browser / network: Playwright-touching functions are mocked.
Run:  python -m pytest -q tests/test_social_browser.py
"""

import pytest

from actions import social_browser as sb


@pytest.fixture
def profiles(tmp_path, monkeypatch):
    monkeypatch.setattr(sb, "PROFILES_ROOT", tmp_path / "social")
    return sb.PROFILES_ROOT


# ── platform normalization ──────────────────────────────────────

@pytest.mark.parametrize("val,expected", [
    ("instagram", "instagram"),
    ("IG", "instagram"),
    ("insta", "instagram"),
    ("x", "twitter"),
    ("Twitter", "twitter"),
    ("fb", "facebook"),
    ("linkedin", "linkedin"),
    ("tiktok", "tiktok"),
    ("myspace", ""),
    ("", ""),
])
def test_normalize_platform(val, expected):
    assert sb.normalize_platform(val) == expected


def test_profile_dir_sanitized():
    p = sb.profile_dir("instagram", "Some.User+tag")
    assert p.parent.name == "instagram"
    assert p.name == "some_user_tag"
    assert ".." not in str(p)


# ── login detection ─────────────────────────────────────────────

@pytest.mark.parametrize("platform,url,expected", [
    ("instagram", "https://www.instagram.com/", True),
    ("instagram", "https://www.instagram.com/accounts/login/", False),
    ("instagram", "https://www.instagram.com/challenge/", False),
    ("twitter", "https://x.com/home", True),
    ("twitter", "https://x.com/i/flow/login", False),
    ("facebook", "https://www.facebook.com/", True),
    ("facebook", "https://www.facebook.com/login/", False),
    ("linkedin", "https://www.linkedin.com/feed/", True),
    ("linkedin", "https://www.linkedin.com/login", False),
    ("tiktok", "https://www.tiktok.com/", True),
    ("tiktok", "https://www.tiktok.com/login", False),
])
def test_is_logged_in_url(platform, url, expected):
    assert sb.is_logged_in_url(platform, url) is expected


# ── connected platforms ─────────────────────────────────────────

def test_connected_platforms_empty(profiles):
    assert sb.connected_platforms() == []


def test_connected_platforms_detects(profiles):
    (profiles / "instagram" / "default").mkdir(parents=True)
    (profiles / "twitter" / "default").mkdir(parents=True)
    assert set(sb.connected_platforms()) == {"instagram", "twitter"}


# ── routing (mocked actions) ────────────────────────────────────

def test_setup_returns_instructions():
    assert "no stored passwords" in sb.social_browser_agent({"action": "setup"})


def test_no_platform_prompts():
    msg = sb.social_browser_agent({"action": "login"})
    assert "Which platform" in msg


def test_login_routes(monkeypatch):
    seen = {}
    monkeypatch.setattr(sb, "_do_login",
                        lambda p, a, pl, sp: seen.update(platform=p, account=a) or True)
    out = sb.social_browser_agent({"action": "login", "platform": "ig", "username": "vince"})
    assert "connected" in out
    assert seen == {"platform": "instagram", "account": "vince"}


def test_status_routes(monkeypatch):
    monkeypatch.setattr(sb, "_check_status", lambda p, a: True)
    assert "active" in sb.social_browser_agent({"action": "status", "platform": "instagram"})


def test_logout_routes(monkeypatch):
    monkeypatch.setattr(sb, "_do_logout", lambda p, a, pl: "LOGOUT")
    assert sb.social_browser_agent({"action": "logout", "platform": "instagram"}) == "LOGOUT"


def test_list_connected(profiles):
    (profiles / "instagram" / "default").mkdir(parents=True)
    out = sb.social_browser_agent({"action": "list"})
    assert "Instagram" in out


def test_unknown_action():
    assert "Unknown social action" in sb.social_browser_agent(
        {"action": "bogus", "platform": "instagram"})


# ── ensure_session compat (mocked) ──────────────────────────────

def test_ensure_session_existing(monkeypatch):
    monkeypatch.setattr(sb, "_check_status", lambda p, a: True)
    res = sb.ensure_session("instagram")
    assert res["success"] is True
    assert res["method"] == "existing_session"


def test_ensure_session_manual_login(monkeypatch):
    monkeypatch.setattr(sb, "_check_status", lambda p, a: False)
    monkeypatch.setattr(sb, "_do_login", lambda p, a, pl, sp: True)
    res = sb.ensure_session("x")
    assert res["success"] is True
    assert res["method"] == "manual_login"


def test_ensure_session_unknown():
    assert sb.ensure_session("myspace")["success"] is False


# ── logout filesystem (no browser) ──────────────────────────────

def test_logout_removes_profile(profiles):
    p = sb.profile_dir("instagram", "")
    p.mkdir(parents=True)
    (p / "Cookies").write_text("x")
    msg = sb._do_logout("instagram", "", None)
    assert "Signed out" in msg
    assert not p.exists()


def test_logout_without_session(profiles):
    assert "No saved" in sb._do_logout("instagram", "", None)


# ── social_login shim delegates ─────────────────────────────────

def test_social_login_shim_delegates(monkeypatch):
    from actions import social_login
    monkeypatch.setattr(sb, "social_browser_agent", lambda params, pl, sp: "DELEGATED")
    assert social_login.social_login_agent({"action": "login"}) == "DELEGATED"


def test_social_login_ensure_delegates(monkeypatch):
    from actions import social_login
    monkeypatch.setattr(sb, "ensure_session",
                        lambda platform, player=None, speak=None, force=False:
                        {"success": True, "message": platform})
    res = social_login.ensure_logged_in("instagram")
    assert res["message"] == "instagram"
