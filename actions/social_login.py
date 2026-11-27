# social_login.py
"""
JARVIS Social Media Login — browser-session edition
────────────────────────────────────────────────────
Thin wrapper around actions/social_browser.py.

Passwords are NO LONGER stored or typed. The user signs in manually in a
visible browser window (normal username + password + 2FA); the session is
saved locally under browser_profiles/social/ (gitignored) and reused.

Public API kept for compatibility:
  * ensure_logged_in(platform, browser, player, speak, force) -> dict
  * social_login_agent(parameters, player, speak) -> str
"""

from actions import social_browser


def ensure_logged_in(
    platform: str,
    browser:  str = "brave",
    player=None,
    speak=None,
    force: bool = False,
) -> dict:
    """Ensure a saved browser session exists; run manual login if needed."""
    return social_browser.ensure_session(platform, player=player, speak=speak, force=force)


def social_login_agent(
    parameters: dict,
    player=None,
    speak=None,
) -> str:
    """Social login entry point (login / status / logout / list / setup)."""
    return social_browser.social_browser_agent(parameters, player, speak)
