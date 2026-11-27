# Email — browser login (no app passwords)

The email agent now defaults to a **real browser session** instead of the
IMAP/SMTP + app-password setup.

## How it works

1. Say **"email login"** (or `email login myname@gmail.com`).
2. A browser window opens to your provider's real sign-in page.
3. You sign in with your **normal email address + password**, and complete
   any 2FA / "confirm it's you" prompt yourself.
4. The session is saved locally and reused. Done — no app passwords, no
   IMAP/SMTP configuration, no long tokens.

Then just ask:
- *"check my email"* / *"any unread emails?"*
- *"search my email for invoice"*
- *"send an email to bob@example.com, subject Hi, body …"*
- *"email status"* / *"email logout"*

## Privacy & security

- **Your password is never read, logged, stored, or transmitted by JARVIS.**
  You type it directly into the provider's own login page.
- Only the browser's session profile (cookies) is persisted, under
  `browser_profiles/email/<provider>/<account>/` — **gitignored**, so it never
  leaves your machine and is never pushed to GitHub.
- Nothing is bypassed: 2FA and captchas are completed by you in the visible
  window.

## Provider support

| Provider | Login + session | Read / search | Send |
|----------|:---:|:---:|:---:|
| Gmail    | ✅ | ✅ | ✅ |
| Outlook / Hotmail / Live | ✅ | ✅ | ✅ |
| Yahoo    | ✅ | — | — |
| Other    | session saved | use `backend='imap'` | use `backend='imap'` |

Web-UI automation can occasionally break if a provider changes its interface;
the legacy IMAP/SMTP path remains available by passing `backend='imap'`.

## Parameters

`action` (login / status / check / unread / search / send / logout / setup),
`email`, `provider`, `to`, `subject`, `body`, `keyword`/`query`, `count`,
`unread_only`, and `backend` (`browser` default, or `imap`).

## Notes

- Login opens a **visible** window and waits up to 5 minutes for you to finish.
- If JARVIS runs as root and the window can't appear, run it as your desktop
  user (e.g. `sudo -u vincent python3 main.py`).
- Tests: `python -m pytest -q tests/test_email_browser.py` (offline, no browser).
