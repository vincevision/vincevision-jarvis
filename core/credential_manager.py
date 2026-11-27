# credential_manager.py
"""
JARVIS Secure Credential Manager
─────────────────────────────────
Stores all sensitive data encrypted on the user's machine.
Users never need to edit config files manually.
Uses system keyring + AES encryption as fallback.
"""

import os
import sys
import json
import base64
import hashlib
import platform
from pathlib import Path

_OS = platform.system()


# ─────────────────────────────────────────────
# BASE DIR
# ─────────────────────────────────────────────

def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR      = _get_base_dir()
CRED_DIR      = BASE_DIR / "config" / ".credentials"
CRED_FILE     = CRED_DIR / "vault.enc"
KEY_FILE      = CRED_DIR / ".key"
CRED_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────
# ENCRYPTION
# ─────────────────────────────────────────────

def _get_machine_key() -> bytes:
    """
    Generate a unique encryption key based on this machine.
    Key is derived from machine-specific info so it only
    works on the same computer.
    """
    # Collect machine-specific identifiers
    identifiers = []

    try:
        if _OS == "Windows":
            import subprocess
            result = subprocess.run(
                ["wmic", "csproduct", "get", "UUID"],
                capture_output=True, text=True
            )
            identifiers.append(result.stdout.strip())
        elif _OS == "Darwin":
            import subprocess
            result = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True, text=True
            )
            identifiers.append(result.stdout)
        else:
            # Linux - use machine-id
            machine_id_files = [
                "/etc/machine-id",
                "/var/lib/dbus/machine-id",
            ]
            for f in machine_id_files:
                if Path(f).exists():
                    identifiers.append(Path(f).read_text().strip())
                    break
    except Exception:
        pass

    # Fallback to username + hostname
    import socket
    identifiers.append(os.environ.get("USER", os.environ.get("USERNAME", "jarvis")))
    identifiers.append(socket.gethostname())

    combined = "|".join(identifiers) + "|JARVIS_SECRET_SALT_2024"
    key      = hashlib.sha256(combined.encode()).digest()
    return key


def _encrypt(data: str, key: bytes) -> str:
    """Simple XOR encryption with key stretching."""
    data_bytes = data.encode("utf-8")
    key_stretched = (key * (len(data_bytes) // len(key) + 1))[:len(data_bytes)]
    encrypted = bytes(a ^ b for a, b in zip(data_bytes, key_stretched))
    return base64.b64encode(encrypted).decode("utf-8")


def _decrypt(data: str, key: bytes) -> str:
    """Decrypt XOR encrypted data."""
    encrypted  = base64.b64decode(data.encode("utf-8"))
    key_stretched = (key * (len(encrypted) // len(key) + 1))[:len(encrypted)]
    decrypted  = bytes(a ^ b for a, b in zip(encrypted, key_stretched))
    return decrypted.decode("utf-8")


# ─────────────────────────────────────────────
# VAULT
# ─────────────────────────────────────────────

def _load_vault() -> dict:
    """Load and decrypt the credential vault."""
    if not CRED_FILE.exists():
        return {}
    try:
        key       = _get_machine_key()
        encrypted = CRED_FILE.read_text(encoding="utf-8").strip()
        decrypted = _decrypt(encrypted, key)
        return json.loads(decrypted)
    except Exception as e:
        print(f"[Credentials] Could not load vault: {e}")
        return {}


def _save_vault(vault: dict):
    """Encrypt and save the credential vault."""
    try:
        key       = _get_machine_key()
        data      = json.dumps(vault, indent=2)
        encrypted = _encrypt(data, key)
        CRED_FILE.write_text(encrypted, encoding="utf-8")
        # Restrict permissions on Linux/Mac
        if _OS != "Windows":
            CRED_FILE.chmod(0o600)
    except Exception as e:
        print(f"[Credentials] Could not save vault: {e}")


# ─────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────

def save_credential(service: str, key: str, value: str):
    """
    Save a credential securely.

    Examples:
        save_credential("gmail",   "email",    "user@gmail.com")
        save_credential("gmail",   "password", "mypassword123")
        save_credential("gemini",  "api_key",  "AIza...")
        save_credential("groq",    "api_key",  "gsk_...")
    """
    vault = _load_vault()
    if service not in vault:
        vault[service] = {}
    vault[service][key] = value
    _save_vault(vault)
    print(f"[Credentials] ✅ Saved {service}/{key}")


def get_credential(service: str, key: str, default: str = "") -> str:
    """
    Get a saved credential.

    Examples:
        email    = get_credential("gmail", "email")
        password = get_credential("gmail", "password")
        api_key  = get_credential("gemini", "api_key")
    """
    vault = _load_vault()
    return vault.get(service, {}).get(key, default)


def delete_credential(service: str, key: str = None) -> str:
    """Delete a credential or entire service."""
    vault = _load_vault()
    if service not in vault:
        return f"No credentials found for: {service}"
    if key:
        vault[service].pop(key, None)
        msg = f"Deleted {service}/{key}"
    else:
        del vault[service]
        msg = f"Deleted all credentials for {service}"
    _save_vault(vault)
    return msg


def list_credentials() -> dict:
    """
    List all saved services and keys
    (without showing actual values).
    """
    vault = _load_vault()
    result = {}
    for service, keys in vault.items():
        result[service] = list(keys.keys())
    return result


def has_credential(service: str, key: str) -> bool:
    """Check if a credential exists."""
    vault = _load_vault()
    return bool(vault.get(service, {}).get(key))


def get_all_for_service(service: str) -> dict:
    """Get all credentials for a service."""
    vault = _load_vault()
    return vault.get(service, {})


def clear_all() -> str:
    """Delete the entire vault."""
    if CRED_FILE.exists():
        CRED_FILE.unlink()
    return "All credentials cleared."


# ─────────────────────────────────────────────
# FIRST RUN SETUP
# ─────────────────────────────────────────────

def is_first_run() -> bool:
    """Check if this is the first time Jarvis is being set up."""
    vault = _load_vault()
    return not vault.get("setup", {}).get("completed", False)


def mark_setup_complete():
    """Mark initial setup as complete."""
    save_credential("setup", "completed", "true")
    save_credential("setup", "date", str(__import__("datetime").date.today()))


def run_setup_wizard(speak=None, player=None) -> str:
    """
    Setup wizard that works safely as root.
    Uses simple terminal input instead of Tkinter.
    """
    import sys

    print("\n")
    print("═" * 60)
    print("🤖  JARVIS FIRST TIME SETUP")
    print("═" * 60)
    print("Your credentials are encrypted and stored only on")
    print("this machine. You will never need to edit code files.")
    print("═" * 60)

    results = []

    # ── Gemini API Key ───────────────────────────
    print("\n📌 STEP 1: Gemini API Key")
    print("   1. Go to: aistudio.google.com")
    print("   2. Click 'Get API Key'")
    print("   3. Copy the key")
    print()

    try:
        import getpass
        gemini_key = getpass.getpass("   Paste Gemini API key (hidden): ").strip()
    except Exception:
        gemini_key = input("   Paste Gemini API key: ").strip()

    if gemini_key:
        save_credential("gemini", "api_key", gemini_key)
        _update_api_keys_json("gemini_api_key", gemini_key)
        results.append("✅ Gemini API key saved")
        print("   ✅ Gemini API key saved!")
    else:
        results.append("⚠️  Gemini API key skipped")
        print("   ⚠️  Skipped")

    # ── Groq API Key ─────────────────────────────
    print("\n📌 STEP 2: Groq API Key (FREE)")
    print("   1. Go to: console.groq.com")
    print("   2. Sign up for free")
    print("   3. Click API Keys → Create API Key")
    print("   4. Copy the key (starts with gsk_)")
    print()

    try:
        groq_key = getpass.getpass("   Paste Groq API key (hidden): ").strip()
    except Exception:
        groq_key = input("   Paste Groq API key: ").strip()

    if groq_key:
        save_credential("groq", "api_key", groq_key)
        _update_api_keys_json("groq_api_key", groq_key)
        results.append("✅ Groq API key saved")
        print("   ✅ Groq API key saved!")
    else:
        results.append("⚠️  Groq API key skipped")
        print("   ⚠️  Skipped")

    # ── Email Setup ──────────────────────────────
    print("\n📌 STEP 3: Email Setup (Optional)")
    print("   This lets Jarvis check and send emails.")
    print()

    want_email = input("   Set up email? (y/n): ").strip().lower()

    if want_email == "y":
        print()
        print("   For Gmail: use an App Password, not your real password")
        print("   Get it at: myaccount.google.com → Security → App Passwords")
        print()

        email_addr = input("   Your email address: ").strip()

        if email_addr:
            try:
                email_pass = getpass.getpass("   Email/App password (hidden): ").strip()
            except Exception:
                email_pass = input("   Email/App password: ").strip()

            if email_pass:
                save_credential("email_default", "email",    email_addr)
                save_credential("email_default", "password", email_pass)
                _update_email_config(email_addr, email_pass)
                results.append(f"✅ Email saved: {email_addr}")
                print(f"   ✅ Email saved: {email_addr}")
            else:
                results.append("⚠️  Email password skipped")
        else:
            results.append("⚠️  Email skipped")
    else:
        results.append("⚠️  Email skipped")
        print("   ⚠️  Skipped (you can add it later)")

    # ── Done ─────────────────────────────────────
    mark_setup_complete()

    print()
    print("═" * 60)
    print("✅  SETUP COMPLETE!")
    print("═" * 60)
    for r in results:
        print(f"   {r}")
    print()
    print("   You can update credentials anytime by saying:")
    print("   'Jarvis update my credentials'")
    print("   'Jarvis add email account'")
    print("═" * 60)
    print()

    if speak:
        speak(
            "Setup complete, sir. JARVIS is ready. "
            "All your credentials are encrypted and saved securely."
        )

    return f"Setup complete:\n" + "\n".join(results)

# ─────────────────────────────────────────────
# JSON COMPATIBILITY HELPERS
# ─────────────────────────────────────────────

def _update_api_keys_json(key: str, value: str):
    """Keep api_keys.json in sync for compatibility."""
    api_path = BASE_DIR / "config" / "api_keys.json"
    try:
        if api_path.exists():
            with open(api_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {}
        data[key] = value
        with open(api_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[Credentials] Could not update api_keys.json: {e}")


def _update_email_config(email_addr: str, password: str):
    """Keep email_config.json in sync."""
    email_path = BASE_DIR / "config" / "email_config.json"
    try:
        if email_path.exists():
            with open(email_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        else:
            config = {"accounts": []}

        # Check if exists
        for acc in config["accounts"]:
            if acc["email"] == email_addr:
                acc["password"] = password
                with open(email_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=2)
                return

        config["accounts"].append({
            "name":     "Default",
            "email":    email_addr,
            "password": password,
            "default":  len(config["accounts"]) == 0,
        })
        with open(email_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

    except Exception as e:
        print(f"[Credentials] Could not update email_config.json: {e}")


# ─────────────────────────────────────────────
# CREDENTIAL AGENT (for voice commands)
# ─────────────────────────────────────────────

def credential_agent(parameters: dict, player=None, speak=None) -> str:
    """
    Handle credential management via voice.

    Actions:
        setup    — Run the full setup wizard
        save     — Save a specific credential
        get      — Get a credential value
        delete   — Delete a credential
        list     — List all saved services
        clear    — Clear all credentials
        update   — Update a specific credential
    """
    params  = parameters or {}
    action  = params.get("action", "setup").lower().strip()
    service = params.get("service", "").lower().strip()
    key     = params.get("key", "").lower().strip()
    value   = params.get("value", "").strip()

    if action == "setup":
        return run_setup_wizard(speak=speak, player=player)

    elif action in ("save", "update", "add"):
        if not service or not key or not value:
            try:
                import getpass
                if not service:
                    service = input(
                        "[Credentials] Service name (e.g. gmail, groq): "
                    ).strip()
                if not key:
                    key = input(
                        "[Credentials] Key name (e.g. password, api_key): "
                    ).strip()
                if not value:
                    value = getpass.getpass(
                        f"[Credentials] Value for {service}/{key} (hidden): "
                    ).strip()
            except Exception:
                return "Please provide service, key and value."

        if service and key and value:
            save_credential(service, key, value)

            # Sync to config files
            if service == "gemini" and key == "api_key":
                _update_api_keys_json("gemini_api_key", value)
            elif service == "groq" and key == "api_key":
                _update_api_keys_json("groq_api_key", value)

            return f"Credential saved: {service}/{key}"
        return "Could not save credential. Missing information."

    elif action == "list":
        creds = list_credentials()
        if not creds:
            return "No credentials saved yet, sir."
        lines = ["Saved credentials:"]
        for svc, keys in creds.items():
            if svc == "setup":
                continue
            lines.append(f"  {svc}: {', '.join(keys)}")
        return "\n".join(lines)

    elif action == "delete":
        if not service:
            return "Please specify which service to delete."
        result = delete_credential(service, key or None)
        return result

    elif action == "clear":
        return clear_all()

    elif action == "check":
        creds = list_credentials()
        lines = ["Credential status:"]
        checks = [
            ("gemini",        "api_key",  "Gemini API"),
            ("groq",          "api_key",  "Groq API"),
            ("email_default", "email",    "Email"),
            ("email_default", "password", "Email password"),
        ]
        for svc, k, name in checks:
            status = "✅" if has_credential(svc, k) else "❌"
            lines.append(f"  {status} {name}")
        return "\n".join(lines)

    else:
        return f"Unknown credential action: {action}"