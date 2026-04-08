from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tgmock._commands import is_python_command, normalize_command
from tgmock._discovery import discover_project
from tgmock.runtime import TgmockSession, snapshot_text

from tests.helpers import (
    write_echo_bot_project,
    write_echo_bot_project_without_config,
    write_go_echo_bot_project,
    write_node_echo_bot_project,
)


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


@pytest.mark.asyncio
async def test_session_start_auto_detects_python_project(tmp_path):
    project_root = write_echo_bot_project_without_config(tmp_path)
    session = TgmockSession()
    try:
        result = await session.start(project_root=project_root)
        assert result["ok"] is True
        assert "bot.py" in result["bot_command"]

        response = await session.send("hello")
        assert response["ok"] is True
        assert "echo: hello" in response["snapshot"]
    finally:
        await session.stop()


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("npm") is None, reason="npm is not installed")
async def test_session_start_auto_detects_node_project(tmp_path):
    project_root = write_node_echo_bot_project(tmp_path)
    session = TgmockSession()
    try:
        result = await session.start(project_root=project_root)
        assert result["ok"] is True
        assert result["bot_command"] == "npm run start"

        response = await session.send("hello")
        assert response["ok"] is True
        assert "echo: hello" in response["snapshot"]
        assert len(response["messages"]) == 1
        assert response["messages"][0]["text"] == "echo: hello"

        tapped = await session.tap("Button A")
        assert tapped["ok"] is True
        assert "tap: btn_a" in tapped["snapshot"]
        assert "echo: hello" not in tapped["snapshot"]
        assert len(tapped["messages"]) == 1
        assert tapped["messages"][0]["text"] == "tap: btn_a"
    finally:
        await session.stop()


def test_snapshot_text_renders_media_messages():
    snapshot = snapshot_text([
        {"method": "sendPhoto", "caption": "look", "photo": {"file_id": "p1"}},
        {"method": "sendVideo", "video": {"file_id": "v1"}},
    ])
    assert "[Bot] [Photo] look" in snapshot
    assert "[Bot] [Video]" in snapshot


@pytest.mark.skipif(shutil.which("go") is None, reason="go is not installed")
def test_discover_project_auto_detects_go_build_and_binary(tmp_path):
    project_root = write_go_echo_bot_project(tmp_path)
    result = discover_project(project_root)
    assert result.runtime == "go"
    assert result.bot_command == ["./.tgmock-go-bot"]
    assert result.build_command == ["go", "build", "-ldflags=-linkmode external", "-o", ".tgmock-go-bot", "."]
