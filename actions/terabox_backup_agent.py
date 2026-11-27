"""Jarvis lifecycle controls for the Telegram-to-TeraBox backup userbot."""

import atexit
import logging
import os
import subprocess
import threading
from pathlib import Path


BACKUP_DIR = Path(__file__).resolve().parents[1] / "telegram-terabox-backup"
_PYTHON = BACKUP_DIR / "venv" / "bin" / "python"
_ENV_FILE = BACKUP_DIR / ".env"
_SESSION_FILE = BACKUP_DIR / "userbot_session.session"
_LOG_FILE = BACKUP_DIR / "jarvis-launch.log"

_logger = logging.getLogger(__name__)
_lock = threading.Lock()
_process: subprocess.Popen | None = None


def terabox_backup_autostart_enabled() -> bool:
    value = os.getenv("JARVIS_TERABOX_BACKUP_AUTOSTART", "1")
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _start() -> str:
    global _process

    with _lock:
        if _process is not None and _process.poll() is None:
            return "Telegram-to-TeraBox backup is already running."
        _process = None

        if not (BACKUP_DIR / "bot.py").is_file():
            return f"Backup tool entry point not found: {BACKUP_DIR / 'bot.py'}"
        if not _ENV_FILE.is_file():
            return (
                f"Backup configuration is missing: {_ENV_FILE}. "
                "Follow the configuration steps in the backup README."
            )
        if not _SESSION_FILE.is_file():
            return (
                "Telegram userbot has not completed its first login. "
                f"Run `{_PYTHON} bot.py` from `{BACKUP_DIR}` in a terminal, "
                "complete Telegram login, then restart Jarvis."
            )
        if not _PYTHON.is_file() or not os.access(_PYTHON, os.X_OK):
            return (
                f"Backup Python environment is missing: {_PYTHON}. "
                f"Create it and install `{BACKUP_DIR / 'requirements.txt'}`."
            )

        try:
            log_file = _LOG_FILE.open("a", encoding="utf-8")
            try:
                os.chmod(_LOG_FILE, 0o600)
                _process = subprocess.Popen(
                    [str(_PYTHON), "-u", "bot.py"],
                    cwd=BACKUP_DIR,
                    stdin=subprocess.DEVNULL,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    close_fds=True,
                )
            finally:
                log_file.close()
        except OSError as exc:
            _process = None
            return f"Could not start the backup userbot: {exc}"

        try:
            exit_code = _process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            exit_code = None
        if exit_code is not None:
            _process = None
            return (
                "Telegram-to-TeraBox backup exited during startup "
                f"(code {exit_code}). Check {_LOG_FILE} for details."
            )

        return (
            "Telegram-to-TeraBox backup started. Registered chats will resume "
            "live media backups automatically; use `/backup <chat_id>` in "
            "Telegram for historical media. Jarvis launch output: "
            f"{_LOG_FILE}"
        )


def _stop() -> str:
    global _process

    with _lock:
        process = _process
        if process is None:
            return "Telegram-to-TeraBox backup was not started by this Jarvis session."
        if process.poll() is not None:
            _process = None
            return "Telegram-to-TeraBox backup is already stopped."

        try:
            process.terminate()
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        except OSError as exc:
            return f"Could not stop the backup userbot: {exc}"

        _process = None
        return "Telegram-to-TeraBox backup stopped."


def _status() -> str:
    global _process

    with _lock:
        if _process is None:
            return "Telegram-to-TeraBox backup is not running in this Jarvis session."
        exit_code = _process.poll()
        if exit_code is not None:
            _process = None
            return (
                "Telegram-to-TeraBox backup exited "
                f"(code {exit_code}). Check {_LOG_FILE} for details."
            )
        return "Telegram-to-TeraBox backup is running."


def _stop_at_exit() -> None:
    result = _stop()
    if result.startswith("Could not stop"):
        _logger.warning(result)


atexit.register(_stop_at_exit)


def terabox_backup_agent(parameters: dict, player=None, speak=None) -> str:
    """Start, stop, or inspect the local Telegram-to-TeraBox backup service."""
    action = str((parameters or {}).get("action", "status")).strip().lower()

    if action == "start":
        return _start()
    if action == "stop":
        return _stop()
    if action == "status":
        return _status()
    if action == "help":
        return (
            "The backup userbot watches chats already registered in "
            "telegram-terabox-backup and automatically uploads new media. "
            "Use `/add <folder>` in a Telegram group to register it, "
            "`/add <chat_id> <folder>` from Saved Messages to register a "
            "chat, and `/backup <chat_id>` for its existing media history."
        )
    return "Unknown action. Use: start, stop, status, help."
