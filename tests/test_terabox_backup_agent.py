import importlib
import sys
from pathlib import Path
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

backup_agent = importlib.import_module("actions.terabox_backup_agent")


def _configure_paths(tmp_path, monkeypatch, *, session=True):
    backup_dir = tmp_path / "telegram-terabox-backup"
    backup_dir.mkdir()
    (backup_dir / "bot.py").touch()
    env_file = backup_dir / ".env"
    env_file.touch()
    session_file = backup_dir / "userbot_session.session"
    if session:
        session_file.touch()
    python = backup_dir / "venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.touch()
    python.chmod(0o755)
    monkeypatch.setattr(backup_agent, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(backup_agent, "_ENV_FILE", env_file)
    monkeypatch.setattr(backup_agent, "_SESSION_FILE", session_file)
    monkeypatch.setattr(backup_agent, "_PYTHON", python)
    monkeypatch.setattr(backup_agent, "_LOG_FILE", backup_dir / "jarvis-launch.log")
    monkeypatch.setattr(backup_agent, "_process", None)
    return backup_dir, python


def test_start_launches_backup_from_its_project_directory(tmp_path, monkeypatch):
    backup_dir, python = _configure_paths(tmp_path, monkeypatch)
    process = Mock()
    process.poll.return_value = None
    process.wait.side_effect = backup_agent.subprocess.TimeoutExpired("bot.py", 1)

    with patch.object(backup_agent.subprocess, "Popen", return_value=process) as popen:
        result = backup_agent.terabox_backup_agent({"action": "start"})

    assert "started" in result.lower()
    popen.assert_called_once()
    args, kwargs = popen.call_args
    assert args[0] == [str(python), "-u", "bot.py"]
    assert kwargs["cwd"] == backup_dir
    assert kwargs["stdin"] == backup_agent.subprocess.DEVNULL
    assert "automatically" in backup_agent.terabox_backup_agent({"action": "help"})


def test_start_refuses_to_launch_without_saved_telegram_session(tmp_path, monkeypatch):
    _configure_paths(tmp_path, monkeypatch, session=False)

    with patch.object(backup_agent.subprocess, "Popen") as popen:
        result = backup_agent.terabox_backup_agent({"action": "start"})

    assert "first login" in result.lower()
    popen.assert_not_called()


def test_status_and_stop_track_the_launched_process(tmp_path, monkeypatch):
    _configure_paths(tmp_path, monkeypatch)
    process = Mock()
    process.poll.return_value = None
    process.wait.side_effect = [
        backup_agent.subprocess.TimeoutExpired("bot.py", 1),
        0,
    ]

    with patch.object(backup_agent.subprocess, "Popen", return_value=process):
        backup_agent.terabox_backup_agent({"action": "start"})
        assert "running" in backup_agent.terabox_backup_agent({"action": "status"})
        assert "stopped" in backup_agent.terabox_backup_agent({"action": "stop"})

    process.terminate.assert_called_once()
    assert process.wait.call_args_list == [
        ((), {"timeout": 1}),
        ((), {"timeout": 10}),
    ]


def test_autostart_can_be_disabled(monkeypatch):
    monkeypatch.setenv("JARVIS_TERABOX_BACKUP_AUTOSTART", "false")
    assert not backup_agent.terabox_backup_autostart_enabled()

    monkeypatch.setenv("JARVIS_TERABOX_BACKUP_AUTOSTART", "1")
    assert backup_agent.terabox_backup_autostart_enabled()
