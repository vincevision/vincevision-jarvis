# actions/email_agent.py
"""
JARVIS Email Agent
Default backend: a real browser session (actions/email_browser.py).
The user signs in once with their normal email + password; the session is
saved locally and reused — no app passwords / IMAP setup required.
Legacy IMAP/SMTP is still available with backend='imap'.
"""

import imaplib
import smtplib
import email
import json
import sys
import time
import threading
import platform
from email.mime.text      import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header         import decode_header
from pathlib              import Path
from datetime             import datetime

_OS = platform.system()


# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = _get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
EMAIL_CONFIG    = BASE_DIR / "config" / "email_config.json"


def _load_email_config() -> dict:
    """Load email credentials from config file."""
    possible_paths = [
        EMAIL_CONFIG,
        Path(__file__).resolve().parent.parent / "config" / "email_config.json",
        Path.home() / ".jarvis" / "email_config.json",
    ]
    for path in possible_paths:
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    print(f"[Email] ✅ Config loaded from: {path}")
                    return data
        except Exception as e:
            print(f"[Email] ⚠️  Error reading {path}: {e}")
    print("[Email] ❌ email_config.json not found")
    return {}


def _save_email_config(config: dict):
    """Save email credentials to config file."""
    EMAIL_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    with open(EMAIL_CONFIG, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    print(f"[Email] 💾 Config saved to: {EMAIL_CONFIG}")


# ─────────────────────────────────────────────
# EMAIL PROVIDERS
# ─────────────────────────────────────────────

PROVIDERS = {
    "gmail": {
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "name":      "Gmail",
    },
    "outlook": {
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "smtp_host": "smtp.office365.com",
        "smtp_port": 587,
        "name":      "Outlook",
    },
    "yahoo": {
        "imap_host": "imap.mail.yahoo.com",
        "imap_port": 993,
        "smtp_host": "smtp.mail.yahoo.com",
        "smtp_port": 587,
        "name":      "Yahoo",
    },
    "hotmail": {
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "smtp_host": "smtp.office365.com",
        "smtp_port": 587,
        "name":      "Hotmail",
    },
    "icloud": {
        "imap_host": "imap.mail.me.com",
        "imap_port": 993,
        "smtp_host": "smtp.mail.me.com",
        "smtp_port": 587,
        "name":      "iCloud",
    },
}


def _detect_provider(email_address: str) -> dict | None:
    """Auto-detect provider from email address."""
    domain  = email_address.split("@")[-1].lower()
    mapping = {
        "gmail.com":      "gmail",
        "googlemail.com": "gmail",
        "outlook.com":    "outlook",
        "hotmail.com":    "hotmail",
        "live.com":       "outlook",
        "yahoo.com":      "yahoo",
        "yahoo.co.uk":    "yahoo",
        "icloud.com":     "icloud",
        "me.com":         "icloud",
    }
    key = mapping.get(domain)
    return PROVIDERS.get(key) if key else None


# ─────────────────────────────────────────────
# IMAP CONNECTION
# ─────────────────────────────────────────────

def _connect_imap(account: dict) -> imaplib.IMAP4_SSL:
    """Connect and login to IMAP server."""
    provider = _detect_provider(account["email"])
    if not provider and "imap_host" not in account:
        raise ValueError(
            f"Unknown email provider for {account['email']}. "
            "Please add imap_host and imap_port to config."
        )

    host = account.get("imap_host") or provider["imap_host"]
    port = int(account.get("imap_port") or provider["imap_port"])

    print(f"[Email] IMAP connecting to {host}:{port}...")
    mail = imaplib.IMAP4_SSL(host, port)
    mail.login(account["email"], account["password"])
    print(f"[Email] ✅ IMAP connected as {account['email']}")
    return mail


def _decode_str(value) -> str:
    """Decode email header string."""
    if value is None:
        return ""
    decoded_parts = decode_header(value)
    result        = ""
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            try:
                result += part.decode(charset or "utf-8", errors="replace")
            except Exception:
                result += part.decode("utf-8", errors="replace")
        else:
            result += str(part)
    return result.strip()


def _get_email_body(msg) -> str:
    """Extract plain text body from email."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype    = part.get_content_type()
            cdispose = str(part.get("Content-Disposition") or "")
            if ctype == "text/plain" and "attachment" not in cdispose:
                try:
                    body = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8",
                        errors="replace"
                    )
                    break
                except Exception:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True).decode(
                msg.get_content_charset() or "utf-8",
                errors="replace"
            )
        except Exception:
            pass
    return body.strip()


# ─────────────────────────────────────────────
# SMTP — SEND EMAIL (FIXED)
# ─────────────────────────────────────────────

def _send_email(account: dict, to: str, subject: str, body: str) -> str:
    """
    Send an email via SMTP.
    Supports port 465 (SSL) and port 587 (STARTTLS).
    Includes full debug logging.
    """
    def log(msg: str):
        print(f"[SMTP] {msg}")

    # ── Resolve provider settings ─────────────────────────────────
    provider = _detect_provider(account["email"])
    if not provider and "smtp_host" not in account:
        return (
            "❌ Unknown email provider. "
            "Please add smtp_host and smtp_port to email_config.json"
        )

    host     = (account.get("smtp_host") or provider["smtp_host"]).strip()
    port     = int(account.get("smtp_port") or provider["smtp_port"])
    username = account["email"].strip()
    password = account["password"].strip()

    log(f"Provider : {host}:{port}")
    log(f"From     : {username}")
    log(f"To       : {to}")
    log(f"Subject  : {subject}")
    log(f"Password : {'set (' + str(len(password)) + ' chars)' if password else 'MISSING!'}")

    if not password:
        return (
            "❌ No password found in email_config.json. "
            "Please add your App Password."
        )

    # ── Build message ─────────────────────────────────────────────
    msg            = MIMEMultipart("alternative")
    msg["From"]    = username
    msg["To"]      = to
    msg["Subject"] = subject
    msg["Date"]    = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")
    msg.attach(MIMEText(body, "plain", "utf-8"))

    # ── Send ──────────────────────────────────────────────────────
    try:
        if port == 465:
            # ── SSL direct connection ──────────────────────────────
            log(f"Using SSL (port 465)...")
            with smtplib.SMTP_SSL(host, port, timeout=30) as server:
                server.set_debuglevel(0)
                log("Logging in...")
                server.login(username, password)
                log(f"Sending to {to}...")
                server.sendmail(username, to, msg.as_string())
                log("✅ Sent via SSL!")

        else:
            # ── STARTTLS connection (port 587) ─────────────────────
            log(f"Using STARTTLS (port {port})...")
            with smtplib.SMTP(host, port, timeout=30) as server:
                server.set_debuglevel(0)
                log("EHLO...")
                server.ehlo()
                log("Starting TLS...")
                server.starttls()
                log("EHLO after TLS...")
                server.ehlo()          # Required after starttls
                log("Logging in...")
                server.login(username, password)
                log(f"Sending to {to}...")
                server.sendmail(username, to, msg.as_string())
                log("✅ Sent via STARTTLS!")

        return (
            f"✅ Email sent successfully!\n"
            f"From   : {username}\n"
            f"To     : {to}\n"
            f"Subject: {subject}"
        )

    except smtplib.SMTPAuthenticationError as e:
        msg_err = (
            f"❌ Authentication failed for {username}.\n"
            f"Error: {e}\n\n"
            f"Fix for Gmail:\n"
            f"  1. Go to myaccount.google.com/apppasswords\n"
            f"  2. Generate App Password for 'Mail'\n"
            f"  3. Use the 16-char password in email_config.json\n"
            f"  4. Make sure 2FA is enabled on your Google account"
        )
        log(msg_err)
        return msg_err

    except smtplib.SMTPConnectError as e:
        msg_err = (
            f"❌ Cannot connect to {host}:{port}\n"
            f"Error: {e}\n"
            f"Check your internet connection and firewall."
        )
        log(msg_err)
        return msg_err

    except smtplib.SMTPServerDisconnected as e:
        msg_err = (
            f"❌ Server disconnected: {e}\n"
            f"Try changing smtp_port to 465 in email_config.json"
        )
        log(msg_err)
        return msg_err

    except smtplib.SMTPException as e:
        msg_err = f"❌ SMTP error: {e}"
        log(msg_err)
        return msg_err

    except ConnectionRefusedError:
        msg_err = (
            f"❌ Connection refused to {host}:{port}\n"
            f"Your network or ISP may be blocking port {port}.\n"
            f"Try switching smtp_port to 465 in email_config.json"
        )
        log(msg_err)
        return msg_err

    except TimeoutError:
        msg_err = (
            f"❌ Connection timed out to {host}:{port}\n"
            f"Check your internet connection."
        )
        log(msg_err)
        return msg_err

    except Exception as e:
        msg_err = f"❌ Unexpected error sending email: {e}"
        log(msg_err)
        return msg_err


# ─────────────────────────────────────────────
# CORE FUNCTIONS
# ─────────────────────────────────────────────

def _check_inbox(
    account:     dict,
    count:       int  = 10,
    unread_only: bool = True
) -> list[dict]:
    """Fetch emails from inbox."""
    mail = _connect_imap(account)
    mail.select("INBOX")

    criteria  = "UNSEEN" if unread_only else "ALL"
    _, data   = mail.search(None, criteria)

    email_ids = data[0].split()
    email_ids = email_ids[-count:]
    emails    = []

    for eid in reversed(email_ids):
        _, msg_data = mail.fetch(eid, "(RFC822)")
        raw_email   = msg_data[0][1]
        msg         = email.message_from_bytes(raw_email)

        subject = _decode_str(msg.get("Subject", "No Subject"))
        sender  = _decode_str(msg.get("From",    "Unknown"))
        date    = _decode_str(msg.get("Date",    ""))
        body    = _get_email_body(msg)

        emails.append({
            "id":      eid.decode(),
            "subject": subject,
            "from":    sender,
            "date":    date,
            "body":    body[:500],
            "unread":  unread_only,
        })

    mail.logout()
    return emails


def _search_emails(
    account: dict,
    keyword: str,
    count:   int = 5
) -> list[dict]:
    """Search emails by keyword."""
    mail = _connect_imap(account)
    mail.select("INBOX")

    _, data   = mail.search(None, f'SUBJECT "{keyword}"')
    email_ids = data[0].split()[-count:]
    emails    = []

    for eid in reversed(email_ids):
        _, msg_data = mail.fetch(eid, "(RFC822)")
        msg         = email.message_from_bytes(msg_data[0][1])
        emails.append({
            "id":      eid.decode(),
            "subject": _decode_str(msg.get("Subject", "")),
            "from":    _decode_str(msg.get("From",    "")),
            "date":    _decode_str(msg.get("Date",    "")),
            "body":    _get_email_body(msg)[:300],
        })

    mail.logout()
    return emails


def _mark_as_read(account: dict, email_id: str) -> str:
    """Mark an email as read."""
    mail = _connect_imap(account)
    mail.select("INBOX")
    mail.store(email_id, "+FLAGS", "\\Seen")
    mail.logout()
    return f"✅ Email {email_id} marked as read."


def _delete_email(account: dict, email_id: str) -> str:
    """Move email to trash."""
    mail = _connect_imap(account)
    mail.select("INBOX")
    mail.store(email_id, "+FLAGS", "\\Deleted")
    mail.expunge()
    mail.logout()
    return f"✅ Email {email_id} deleted."


def _get_unread_count(account: dict) -> int:
    """Get number of unread emails."""
    mail    = _connect_imap(account)
    mail.select("INBOX")
    _, data = mail.search(None, "UNSEEN")
    count   = len(data[0].split()) if data[0] else 0
    mail.logout()
    return count


# ─────────────────────────────────────────────
# BACKGROUND MONITOR
# ─────────────────────────────────────────────

_monitor_thread  = None
_monitor_running = False
_last_count      = {}


def _monitor_loop(account: dict, interval: int, speak, player):
    """Background thread that checks for new emails."""
    global _monitor_running, _last_count

    account_key = account["email"]

    while _monitor_running:
        try:
            count = _get_unread_count(account)

            if account_key not in _last_count:
                _last_count[account_key] = count
                if player:
                    player.write_log(
                        f"[Email] 📧 Monitoring {account_key} "
                        f"— {count} unread"
                    )

            elif count > _last_count[account_key]:
                new_count = count - _last_count[account_key]
                _last_count[account_key] = count

                message = (
                    f"Sir, you have {new_count} new "
                    f"email{'s' if new_count > 1 else ''}."
                )

                if player:
                    player.write_log(f"[Email] 🔔 {message}")

                if speak:
                    try:
                        new_emails = _check_inbox(
                            account, count=new_count
                        )
                        for em in new_emails[:2]:
                            speak(
                                f"New email from "
                                f"{em['from'].split('<')[0].strip()}. "
                                f"Subject: {em['subject']}."
                            )
                    except Exception:
                        speak(message)
            else:
                _last_count[account_key] = count

        except Exception as e:
            print(f"[Email] Monitor error: {e}")

        time.sleep(interval)


def _start_monitor(
    account:  dict,
    interval: int,
    speak,
    player
) -> str:
    """Start background email monitoring."""
    global _monitor_thread, _monitor_running

    if _monitor_running:
        return "Email monitor is already running, sir."

    _monitor_running = True
    _monitor_thread  = threading.Thread(
        target = _monitor_loop,
        args   = (account, interval, speak, player),
        daemon = True
    )
    _monitor_thread.start()
    return (
        f"✅ Email monitoring started for {account['email']}. "
        f"Checking every {interval} seconds."
    )


def _stop_monitor() -> str:
    """Stop background email monitoring."""
    global _monitor_running
    _monitor_running = False
    return "✅ Email monitoring stopped."


# ─────────────────────────────────────────────
# FORMAT OUTPUT
# ─────────────────────────────────────────────

def _format_emails(emails: list[dict], max_body: int = 200) -> str:
    """Format email list for display."""
    if not emails:
        return "No emails found."

    lines = []
    for i, em in enumerate(emails, 1):
        lines.append(f"{'─' * 50}")
        lines.append(f"#{i}  From   : {em['from']}")
        lines.append(f"    Subject: {em['subject']}")
        lines.append(f"    Date   : {em['date']}")
        if em.get("body"):
            body = em["body"][:max_body]
            lines.append(f"    Preview: {body}...")
    lines.append(f"{'─' * 50}")
    return "\n".join(lines)


# ─────────────────────────────────────────────
# SETUP HELPER
# ─────────────────────────────────────────────

def _setup_instructions() -> str:
    return """
📧 EMAIL SETUP REQUIRED
════════════════════════════════════════════════

Save this file to: config/email_config.json

{
  "accounts": [
    {
      "name":      "My Gmail",
      "email":     "yourname@gmail.com",
      "password":  "abcd efgh ijkl mnop",
      "smtp_host": "smtp.gmail.com",
      "smtp_port": 587,
      "imap_host": "imap.gmail.com",
      "imap_port": 993,
      "default":   true
    }
  ]
}

⚠️  GMAIL — App Password Setup:
  1. Go to myaccount.google.com
  2. Security → 2-Step Verification (must be ON)
  3. Security → App Passwords
  4. Select app: Mail → Generate
  5. Copy the 16-character password
  6. Paste it into email_config.json (with spaces is fine)
  7. Do NOT use your regular Google password

⚠️  OUTLOOK / HOTMAIL:
  1. Go to account.microsoft.com
  2. Security → Advanced Security Options
  3. Enable Two-step verification
  4. Create App Password → copy it

⚠️  YAHOO:
  1. Go to Yahoo Account Security
  2. Generate App Password for Mail
  3. Use that password in config

After setup say:
  "Jarvis check my emails"
  "Jarvis send an email to john@example.com"
  "Jarvis monitor my emails"
════════════════════════════════════════════════
"""


# ─────────────────────────────────────────────
# MAIN AGENT
# ─────────────────────────────────────────────

def email_agent(
    parameters: dict,
    player=None,
    speak=None,
) -> str:
    """
    Main email agent entry point.

    Actions:
        check       — Check inbox for new/unread emails
        send        — Send an email
        search      — Search emails by keyword
        unread      — Get unread count
        mark_read   — Mark email as read
        delete      — Delete an email
        monitor     — Start background monitoring
        stop        — Stop monitoring
        setup       — Show setup instructions
        add_account — Add a new email account
    """
    params = parameters or {}
    action = params.get("action", "check").lower().strip()

    if player:
        player.write_log(f"[Email] Action: {action}")

    # ── Browser backend (default): sign in once, reuse the saved session ──
    backend = str(params.get("backend", "browser")).lower().strip()
    if backend != "imap":
        from actions.email_browser import email_browser_agent
        return email_browser_agent(params, player, speak)

    # ── Setup / Help ──────────────────────────────────────────────
    if action in ("setup", "help", "instructions"):
        return _setup_instructions()

    # ── Stop Monitor ──────────────────────────────────────────────
    if action == "stop":
        return _stop_monitor()

    # ── Add Account ───────────────────────────────────────────────
    if action == "add_account":
        email_addr = params.get("email",    "").strip()
        password   = params.get("password", "").strip()
        name       = params.get("name", email_addr)

        if not email_addr or not password:
            return (
                "Please provide email and password. "
                "Example: 'Add email account myname@gmail.com "
                "with password myapppassword'"
            )

        config = _load_email_config()
        if "accounts" not in config:
            config["accounts"] = []

        for acc in config["accounts"]:
            if acc["email"] == email_addr:
                acc["password"] = password
                acc["name"]     = name
                _save_email_config(config)
                return f"✅ Updated account: {email_addr}"

        is_first = len(config["accounts"]) == 0
        config["accounts"].append({
            "name":     name,
            "email":    email_addr,
            "password": password,
            "default":  is_first,
        })
        _save_email_config(config)
        return (
            f"✅ Email account added: {email_addr}"
            f"{' — set as default.' if is_first else '.'}"
        )

    # ── Load Account ──────────────────────────────────────────────
    config   = _load_email_config()
    accounts = config.get("accounts", [])

    if not accounts:
        return (
            "❌ No email accounts configured, sir.\n"
            "Say 'Jarvis email setup' for instructions.\n"
            "Or say 'add email account yourname@gmail.com "
            "with password yourapppassword'"
        )

    # Get specified or default account
    account_name = params.get("account", "").lower()
    account      = None

    if account_name:
        for acc in accounts:
            if (account_name in acc.get("name",  "").lower() or
                    account_name in acc.get("email", "").lower()):
                account = acc
                break

    if not account:
        account = next(
            (a for a in accounts if a.get("default")),
            accounts[0]
        )

    if player:
        player.write_log(f"[Email] Using account: {account.get('email','?')}")

    # ── Execute Actions ───────────────────────────────────────────
    try:

        # ── CHECK ─────────────────────────────────────────────────
        if action == "check":
            count       = int(params.get("count", 10))
            unread_only = params.get("unread_only", True)
            if isinstance(unread_only, str):
                unread_only = unread_only.lower() != "false"

            if player:
                player.write_log(
                    f"[Email] Checking inbox for {account['email']}..."
                )

            emails = _check_inbox(
                account, count=count, unread_only=unread_only
            )

            if not emails:
                msg = (
                    f"No {'unread ' if unread_only else ''}emails, sir."
                )
                if speak:
                    speak(msg)
                return msg

            if speak:
                if len(emails) == 1:
                    em = emails[0]
                    speak(
                        f"You have one new email, sir. "
                        f"From {em['from'].split('<')[0].strip()}. "
                        f"Subject: {em['subject']}."
                    )
                else:
                    speak(
                        f"You have {len(emails)} unread emails, sir. "
                        f"The latest is from "
                        f"{emails[0]['from'].split('<')[0].strip()}."
                    )

            return _format_emails(emails)

        # ── SEND ──────────────────────────────────────────────────
        elif action == "send":
            to      = params.get("to",      "").strip()
            subject = params.get("subject", "").strip()
            body    = params.get("body",    "").strip()

            if not to:
                return "❌ Please specify a recipient email address, sir."
            if not subject:
                subject = "Message from JARVIS"
            if not body:
                return "❌ Please provide a message body, sir."

            if player:
                player.write_log(
                    f"[Email] Sending to {to} — Subject: {subject}"
                )

            result = _send_email(account, to, subject, body)

            if speak:
                if "✅" in result:
                    speak(f"Email sent to {to}, sir.")
                else:
                    speak(
                        "Email failed to send, sir. "
                        "Check the logs for details."
                    )
            return result

        # ── SEARCH ────────────────────────────────────────────────
        elif action == "search":
            keyword = params.get(
                "keyword", params.get("query", "")
            ).strip()
            if not keyword:
                return "❌ Please provide a search keyword, sir."

            emails = _search_emails(account, keyword, count=5)
            if not emails:
                return f"No emails found matching '{keyword}', sir."

            if speak:
                speak(
                    f"Found {len(emails)} emails matching {keyword}."
                )
            return _format_emails(emails)

        # ── UNREAD ────────────────────────────────────────────────
        elif action == "unread":
            count = _get_unread_count(account)
            msg   = (
                f"You have {count} unread "
                f"email{'s' if count != 1 else ''}, sir."
                if count > 0 else
                "No unread emails, sir."
            )
            if speak:
                speak(msg)
            return msg

        # ── MARK READ ─────────────────────────────────────────────
        elif action == "mark_read":
            email_id = params.get("email_id", "").strip()
            if not email_id:
                return "❌ Please provide the email ID to mark as read."
            return _mark_as_read(account, email_id)

        # ── DELETE ────────────────────────────────────────────────
        elif action == "delete":
            email_id = params.get("email_id", "").strip()
            if not email_id:
                return "❌ Please provide the email ID to delete."
            return _delete_email(account, email_id)

        # ── MONITOR ───────────────────────────────────────────────
        elif action == "monitor":
            interval = int(params.get("interval", 60))
            return _start_monitor(account, interval, speak, player)

        else:
            return (
                f"❌ Unknown email action: '{action}'.\n"
                "Available actions: check, send, search, unread, "
                "mark_read, delete, monitor, stop, setup, add_account"
            )

    except imaplib.IMAP4.error as e:
        err = str(e)
        if "authentication failed" in err.lower():
            return (
                "❌ Authentication failed, sir.\n"
                "For Gmail: use an App Password, not your Google password.\n"
                "Go to: myaccount.google.com/apppasswords\n"
                "Say 'email setup' for full instructions."
            )
        return f"❌ Email connection error: {e}"

    except ConnectionRefusedError as e:
        return (
            f"❌ Connection refused: {e}\n"
            "Your network may be blocking SMTP/IMAP ports.\n"
            "Try a different network or VPN."
        )

    except TimeoutError as e:
        return (
            f"❌ Connection timed out: {e}\n"
            "Check your internet connection."
        )

    except Exception as e:
        print(f"[Email] ❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return f"❌ Email agent error: {e}"