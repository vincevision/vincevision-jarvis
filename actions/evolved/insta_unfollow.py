import time
import random
import json
from pathlib import Path
from datetime import datetime

# Graceful imports
try:
    from instagrapi import Client
    from instagrapi.exceptions import (
        LoginRequired, BadPassword, ChallengeRequired, ClientError, TwoFactorRequired
    )
    PACKAGE_OK = True
except ImportError:
    PACKAGE_OK = False

# ── Config ────────────────────────────────────────────────────────────────────
CREDENTIALS_FILE = Path.home() / ".jarvis_credentials" / "insta_unfollow.json"
LOG_DIR          = Path.home() / "JARVIS_logs" / "insta_unfollow"

def _log(player, msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[INSTA_UNFOLLOW] [{ts}] {msg}"
    print(line)
    if player:
        try: player.write_log(line[:300])
        except: pass

def _speak(speak, msg: str):
    if speak:
        try: speak(msg)
        except: pass

def _save_creds(data: dict):
    CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_FILE.write_text(json.dumps(data, indent=2))

def _load_creds() -> dict:
    try:
        if CREDENTIALS_FILE.exists():
            return json.loads(CREDENTIALS_FILE.read_text())
    except: pass
    return {}

def insta_unfollow(parameters: dict, player=None, speak=None) -> str:
    action   = parameters.get("action", "run")
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    if not PACKAGE_OK:
        _speak(speak, "The 'instagrapi' package is not installed. Please install it to use this tool.")
        return "Error: 'instagrapi' package not found. Please install it."

    # ── Get credentials ───────────────────────────────────────────────────────
    creds_data = _load_creds()
    username = parameters.get("username") or creds_data.get("username", "")
    password = parameters.get("password") or creds_data.get("password", "")
    
    # instagrapi session settings are more robust than just username/password
    session_settings_path = CREDENTIALS_FILE

    # ── Check missing credentials ─────────────────────────────────────────────
    if not username or not password:
        # If session settings exist, we might not need explicit username/password for login
        # but for initial setup or if session expires, they are needed.
        # This check is for the case where no session or explicit creds are provided.
        if not session_settings_path.exists():
            return (
                f"Credentials needed. Please say: "
                f"use insta_unfollow with username YOUR_USERNAME and password YOUR_PASSWORD"
            )

    _log(player, f"Starting {action} for {username if username else 'Instagram'}")
    _speak(speak, f"Starting {action}, sir.")

    # ── Main logic here ───────────────────────────────────────────────────────
    if action == "run":
        cl = Client()
        cl.delay_range = [3, 8] # Random delays between 3 to 8 seconds
        cl.set_user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36")

        # Custom challenge code handler for 2FA
        def challenge_code_handler(username, choice):
            _speak(speak, f"Instagram requires a 2FA code. Please check your {choice} for a code.")
            _speak(speak, "What is the 2FA code?")
            # In a real JARVIS, player.ask_user_input() would be used here.
            # For this context, we'll use input() which blocks execution.
            code = input(f"Enter 2FA code sent to {choice} for {username}: ")
            return code
        cl.challenge_code_handler = challenge_code_handler

        try:
            # Try to load session settings first
            if session_settings_path.exists():
                _log(player, "Attempting to load existing session settings...")
                cl.load_settings(session_settings_path)
                _log(player, "Session settings loaded. Verifying login state...")
                # Verify if the session is still valid
                try:
                    cl.get_timeline_feed()
                    _speak(speak, "Successfully logged in using saved session.")
                except LoginRequired:
                    _log(player, "Saved session expired or invalid. Attempting fresh login.")
                    cl.login(username, password)
                    _speak(speak, "Successfully logged in with username and password.")
                    _save_creds({"username": username, "password": password}) # Update creds if fresh login successful
                    cl.dump_settings(session_settings_path) # Save new session settings
            else:
                _log(player, "No session settings found. Attempting fresh login.")
                cl.login(username, password)
                _speak(speak, "Successfully logged in with username and password.")
                _save_creds({"username": username, "password": password}) # Save username/password
                cl.dump_settings(session_settings_path) # Save new session settings

        except BadPassword:
            _speak(speak, "Login failed: Incorrect password. Please check your credentials.")
            return "Error: Incorrect password. Please provide the correct password."
        except TwoFactorRequired:
            _speak(speak, "Login failed: Two-factor authentication required but code not provided or invalid.")
            return "Error: Two-factor authentication required. Please try again and provide the code."
        except ChallengeRequired:
            _speak(speak, "Login failed: Instagram challenge required. Please try again later or check your account manually.")
            return "Error: Instagram challenge required. Account might be locked or suspicious activity detected."
        except ClientError as e:
            _speak(speak, f"An Instagram client error occurred during login: {e}")
            return f"Error: Instagram client error during login: {e}"
        except Exception as e:
            _speak(speak, f"An unexpected error occurred during login: {e}")
            return f"Error: Unexpected error during login: {e}"

        _log(player, "Fetching user data...")
        _speak(speak, "Fetching your followers and following lists, sir. This may take a moment.")

        try:
            user_id = cl.user_id
            followers = cl.user_followers(user_id)
            followings = cl.user_following(user_id)
        except ClientError as e:
            _speak(speak, f"Failed to fetch followers or followings: {e}")
            return f"Error: Failed to fetch Instagram data: {e}"
        except Exception as e:
            _speak(speak, f"An unexpected error occurred while fetching data: {e}")
            return f"Error: Unexpected error fetching data: {e}"

        follower_ids = {user.pk for user in followers.values()}
        to_unfollow = [user for user in followings.values() if user.pk not in follower_ids]

        if not to_unfollow:
            _speak(speak, "Good news, sir. All users you follow are following you back, or you are not following anyone who doesn't follow you back.")
            return "No users found to unfollow who don't follow you back."

        max_unfollow_count = parameters.get("count", 50)
        unfollowed_count = 0
        total_to_unfollow = len(to_unfollow)
        
        log_file_name = f"unfollowed_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        session_log_path = LOG_DIR / log_file_name

        _log(player, f"Found {total_to_unfollow} users who don't follow you back. Starting unfollow process (max {max_unfollow_count}).")
        _speak(speak, f"Found {total_to_unfollow} users who don't follow you back. I will unfollow up to {max_unfollow_count} of them.")

        with open(session_log_path, "w") as f_log:
            f_log.write(f"--- Instagram Unfollow Log - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            f_log.write(f"Session initiated by user: {username}\n")
            f_log.write(f"Maximum unfollows for this session: {max_unfollow_count}\n\n")
            f_log.write("Unfollowed Users:\n")

            for i, user in enumerate(to_unfollow):
                if unfollowed_count >= max_unfollow_count:
                    _speak(speak, f"Reached the maximum unfollow limit of {max_unfollow_count} for this session.")
                    _log(player, f"Reached max unfollow limit ({max_unfollow_count}). Stopping.")
                    break

                try:
                    _log(player, f"Attempting to unfollow: {user.username} (ID: {user.pk})")
                    cl.user_unfollow(user.pk)
                    unfollowed_count += 1
                    f_log.write(f"- {user.username} (ID: {user.pk}) at {datetime.now().strftime('%H:%M:%S')}\n")
                    _log(player, f"Successfully unfollowed: {user.username}")

                    if unfollowed_count % 10 == 0:
                        percent = (unfollowed_count / min(total_to_unfollow, max_unfollow_count)) * 100
                        _speak(speak, f"Processed {unfollowed_count} of {min(total_to_unfollow, max_unfollow_count)} users. Progress: {percent:.0f} percent.")
                        _log(player, f"Progress: {unfollowed_count} of {min(total_to_unfollow, max_unfollow_count)} users unfollowed.")

                    delay = random.randint(3, 8)
                    _log(player, f"Waiting for {delay} seconds before next unfollow.")
                    time.sleep(delay)

                except ClientError as e:
                    _speak(speak, f"Failed to unfollow {user.username}: {e}. Skipping this user.")
                    _log(player, f"Error unfollowing {user.username}: {e}")
                    f_log.write(f"- FAILED to unfollow {user.username} (ID: {user.pk}): {e}\n")
                    # Continue to the next user
                    delay = random.randint(3, 8) # Still wait to avoid rapid retries
                    time.sleep(delay)
                except Exception as e:
                    _speak(speak, f"An unexpected error occurred while unfollowing {user.username}: {e}. Skipping this user.")
                    _log(player, f"Unexpected error unfollowing {user.username}: {e}")
                    f_log.write(f"- UNEXPECTED ERROR unfollowing {user.username} (ID: {user.pk}): {e}\n")
                    delay = random.randint(3, 8)
                    time.sleep(delay)

        _speak(speak, f"Done. Processed {unfollowed_count} items. Log saved to {session_log_path.name}")
        return f"Done. Processed {unfollowed_count} items. Log saved to {session_log_path}"

    elif action == "status":
        _speak(speak, "Status monitoring is not yet fully implemented for this tool, sir.")
        return "Status: Not fully implemented."
    elif action == "stop":
        _speak(speak, "Stopping current operations is not yet fully implemented for this tool, sir.")
        return "Stop: Not fully implemented."
    elif action == "setup":
        _speak(speak, "Setup options are not yet fully implemented for this tool, sir. Credentials are saved automatically on first successful login.")
        return "Setup: Not fully implemented. Credentials are saved automatically."
    else:
        _speak(speak, f"Unknown action: {action}. Please use 'run', 'status', 'stop', or 'setup'.")
        return f"Error: Unknown action '{action}'."

DECLARATION = {
    "name": "insta_unfollow",
    "description": "Automates unfollowing Instagram users who do not follow you back, with random delays, progress updates, and logging of unfollowed accounts.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action":   {"type": "STRING",  "description": "run | status | stop | setup"},
            "username": {"type": "STRING",  "description": "Account username"},
            "password": {"type": "STRING",  "description": "Account password"},
            "count":    {"type": "INTEGER", "description": "Max items to process per session (default 50)."},
            "delay":    {"type": "NUMBER",  "description": "Delay between actions in seconds (default random 3-8s)."},
        },
        "required": []
    }
}