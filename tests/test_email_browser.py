"""
Offline tests for the browser email backend.

No real browser / network: Playwright-touching functions are mocked.
Run:  python -m pytest -q tests/test_email_browser.py
"""

import pytest

from actions import email_browser as eb


@pytest.fixture
def profiles(tmp_path, monkeypatch):
    monkeypatch.setattr(eb, "PROFILES_ROOT", tmp_path / "email")
    return eb.PROFILES_ROOT


# ── provider detection ──────────────────────────────────────────

@pytest.mark.parametrize("val,expected", [
    ("alice@gmail.com", "gmail"),
    ("alice@googlemail.com", "gmail"),
    ("bob@hotmail.com", "outlook"),
    ("carol@outlook.com", "outlook"),
    ("dave@yahoo.com", "yahoo"),
    ("eve@corp.io", "custom"),
    ("gmail", "gmail"),
    ("OUTLOOK", "outlook"),
    ("", ""),
])
def test_detect_provider(val, expected):
    assert eb.detect_provider(val) == expected


def test_profile_dir_sanitized():
    p = eb.profile_dir("gmail", "Alice.Smith+tag@gmail.com")
    assert p.parent.name == "gmail"
    assert "alice_smith_tag_gmail_com" == p.name
    assert ".." not in str(p)


def test_profile_dir_default():
    assert eb.profile_dir("gmail", "").name == "default"


# ── login detection ─────────────────────────────────────────────

@pytest.mark.parametrize("provider,url,expected", [
    ("gmail", "https://mail.google.com/mail/u/0/#inbox", True),
    ("gmail", "https://accounts.google.com/signin", False),
    ("outlook", "https://outlook.live.com/mail/0/inbox", True),
    ("outlook", "https://login.live.com/", False),
    ("yahoo", "https://mail.yahoo.com/d/folders/1", True),
    ("yahoo", "https://login.yahoo.com/", False),
])
def test_is_logged_in_url(provider, url, expected):
    assert eb.is_logged_in_url(provider, url) is expected


# ── formatting ──────────────────────────────────────────────────

def test_format_emails_empty():
    assert "No emails" in eb.format_emails([])


def test_format_emails_flags_unread_and_truncates():
    out = eb.format_emails([
        {"from": "Bob <bob@x.com>", "subject": "Hi", "body": "y" * 500, "unread": True},
    ], max_body=50)
    assert "🔵" in out
    assert "Bob" in out and "Hi" in out
    assert "…" in out


# ── account resolution ──────────────────────────────────────────

def test_resolve_account_from_email():
    assert eb._resolve_account({"email": "a@gmail.com"}) == ("gmail", "a@gmail.com")


def test_resolve_account_explicit_provider():
    assert eb._resolve_account({"provider": "outlook"})[0] == "outlook"


def test_resolve_account_custom_domain():
    assert eb._resolve_account({"email": "a@corp.io"})[0] == "custom"


# ── routing (mocked actions) ────────────────────────────────────

def test_setup_returns_instructions():
    assert "no app passwords" in eb.email_browser_agent({"action": "setup"})


def test_no_account_prompts_login():
    msg = eb.email_browser_agent({"action": "check"})
    assert "email login" in msg


def test_login_routes(monkeypatch):
    seen = {}
    monkeypatch.setattr(eb, "_do_login", lambda p, e, pl, sp: seen.update(provider=p, email=e) or "LOGIN")
    out = eb.email_browser_agent({"action": "login", "email": "a@gmail.com"})
    assert out == "LOGIN"
    assert seen == {"provider": "gmail", "email": "a@gmail.com"}


def test_check_routes(monkeypatch):
    seen = {}
    monkeypatch.setattr(eb, "_do_read",
                        lambda p, e, c, u, pl, sp: seen.update(count=c, unread=u) or "READ")
    out = eb.email_browser_agent({"action": "check", "email": "a@gmail.com", "count": 7})
    assert out == "READ"
    assert seen["count"] == 7


def test_unread_forces_unread_only(monkeypatch):
    seen = {}
    monkeypatch.setattr(eb, "_do_read",
                        lambda p, e, c, u, pl, sp: seen.update(unread=u) or "READ")
    eb.email_browser_agent({"action": "unread", "email": "a@gmail.com"})
    assert seen["unread"] is True


def test_send_routes(monkeypatch):
    seen = {}
    monkeypatch.setattr(eb, "_do_send",
                        lambda p, e, to, subj, body, pl, sp: seen.update(to=to, body=body) or "SENT")
    out = eb.email_browser_agent({"action": "send", "email": "a@gmail.com",
                                  "to": "b@x.com", "subject": "S", "body": "B"})
    assert out == "SENT"
    assert seen == {"to": "b@x.com", "body": "B"}


def test_search_requires_keyword():
    assert "keyword" in eb.email_browser_agent({"action": "search", "email": "a@gmail.com"})


def test_logout_routes(monkeypatch):
    monkeypatch.setattr(eb, "_do_logout", lambda p, e, pl: "LOGOUT")
    assert eb.email_browser_agent({"action": "logout", "email": "a@gmail.com"}) == "LOGOUT"


def test_unknown_action():
    assert "Unknown email action" in eb.email_browser_agent({"action": "bogus", "email": "a@gmail.com"})


# ── session guard (no browser launched) ─────────────────────────

def test_read_without_session_never_launches_browser(profiles):
    msg = eb._do_read("gmail", "a@gmail.com", 10, False, None, None)
    assert "No saved" in msg and "email login" in msg


def test_status_without_session(profiles):
    msg = eb._do_status("gmail", "a@gmail.com", None)
    assert "Not connected" in msg


def test_logout_without_session(profiles):
    assert "No saved session" in eb._do_logout("gmail", "a@gmail.com", None)


def test_logout_removes_profile(profiles):
    p = eb.profile_dir("gmail", "a@gmail.com")
    p.mkdir(parents=True)
    (p / "Cookies").write_text("x")
    msg = eb._do_logout("gmail", "a@gmail.com", None)
    assert "Signed out" in msg
    assert not p.exists()
