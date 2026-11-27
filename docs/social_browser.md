# Social login — browser sessions (no stored passwords)

Social accounts now connect the same way as email: **sign in once in a real
browser window**, and the session is saved locally and reused.

## How it works

1. Say **"social login instagram"** (or `twitter`, `facebook`, `linkedin`, `tiktok`).
2. A browser window opens to the platform's real sign-in page.
3. You sign in with your **normal username + password**, and complete any
   2FA / checkpoint yourself.
4. The session is saved locally. The Instagram/social agents then work off it.

Also: `social status`, `social logout`, `social list`.

Instagram specifically: say **"instagram login"** — the browser opens, you sign
in yourself, and the session persists in `browser_profiles/instagram`.

## Privacy & security

- **Your password is never read, logged, stored, or transmitted by JARVIS.**
  You type it directly into the platform's own login page.
- Only the browser session profile (cookies) is persisted, under
  `browser_profiles/social/<platform>/…` (and `browser_profiles/instagram` for
  the Instagram agent) — **gitignored**, never pushed to GitHub.
- Nothing is bypassed: 2FA and checkpoints are completed by you in the window.

## What changed

- New `actions/social_browser.py` — manual login + session management for
  Instagram, X/Twitter, Facebook, LinkedIn, TikTok.
- `actions/social_login.py` is now a thin wrapper around it. The old
  password-storage + credential-typing flow was removed.
- `actions/instagram_agent.py` login is now manual: it opens the login page and
  waits for you to sign in (no username/password typing, no `setup` password).

## Supported platforms

Instagram · X (Twitter) · Facebook · LinkedIn · TikTok

## Notes

- Login opens a **visible** window and waits up to 5 minutes.
- If JARVIS runs as root and no window appears, run it as your desktop user
  (e.g. `sudo -u <your-user> python3 main.py`).
- Tests: `python -m pytest -q tests/test_social_browser.py` (offline, no browser).
