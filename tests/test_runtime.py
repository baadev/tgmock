from __future__ import annotations

from pathlib import Path

import pytest

from tgmock._commands import is_python_command, normalize_command
from tgmock.runtime import TgmockSession

from tests.helpers import write_echo_bot_project


def test_normalize_command_handles_quotes():
    assert normalize_command('python -c "print(1)"') == ["python", "-c", "print(1)"]


def test_is_python_command_detects_full_paths_and_shell_wrappers():
    assert is_python_command("/tmp/venv/bin/python bot.py") is True
    assert is_python_command(["/tmp/venv/bin/python", "bot.py"]) is True
    assert is_python_command(["bash", "-lc", "python bot.py"]) is True


@pytest.mark.asyncio
async def test_session_start_uses_explicit_project_root(tmp_path, monkeypatch):
    project_root = write_echo_bot_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    session = TgmockSession()
    try:
        result = await session.start(project_root=project_root)
        assert result["ok"] is True
        assert Path(result["project_root"]) == project_root

        response = await session.send("hello")
        assert response["ok"] is True
        assert "echo: hello" in response["snapshot"]
    finally:
        await session.stop()


@pytest.mark.asyncio
async def test_build_command_does_not_use_shell(tmp_path):
    project_root = write_echo_bot_project(tmp_path)
    session = TgmockSession()
    try:
        result = await session.start(
            project_root=project_root,
            build_command="echo safe > built.txt",
        )
        assert result["ok"] is True
        assert not (project_root / "built.txt").exists()
    finally:
        await session.stop()


@pytest.mark.asyncio
async def test_session_restart_keeps_server_running(tmp_path):
    project_root = write_echo_bot_project(tmp_path)
    session = TgmockSession()
    try:
        await session.start(project_root=project_root)
        first = await session.send("before restart")
        assert "echo: before restart" in first["snapshot"]

        restarted = await session.restart(project_root=project_root)
        assert restarted["ok"] is True

        second = await session.send("after restart")
        assert "echo: after restart" in second["snapshot"]
    finally:
        await session.stop()
