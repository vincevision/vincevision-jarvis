import importlib.util
import re
from pathlib import Path


BACKUP_DIR = Path(__file__).resolve().parents[1] / "telegram-terabox-backup"
SPEC = importlib.util.spec_from_file_location(
    "telegram_backup_command_patterns",
    BACKUP_DIR / "command_patterns.py",
)
COMMAND_PATTERNS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMMAND_PATTERNS)


def test_bot_command_with_own_username_is_matched():
    pattern = re.compile(COMMAND_PATTERNS.command_pattern("status", "MyBackupBot"))

    assert pattern.match("/status@MyBackupBot")
    assert pattern.match("/status@MyBackupBot ")
    assert not pattern.match("/status@AnotherBot")
    assert not pattern.match("/status")


def test_unmentioned_commands_still_work():
    pattern = re.compile(COMMAND_PATTERNS.command_pattern("add"))

    assert pattern.match("/add")
    assert pattern.match("/add /MyBackups")
    assert not pattern.match("/add@SomeOtherBot /MyBackups")
