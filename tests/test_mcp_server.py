from __future__ import annotations

import json
from pathlib import Path

import pytest

from tgmock import mcp_server

from tests.helpers import write_echo_bot_project


@pytest.mark.asyncio
async def test_dispatch_tool_smoke_flow(tmp_path):
    project_root = write_echo_bot_project(tmp_path)
    try:
        started = await mcp_server.dispatch_tool("tg_start", {"project_root": str(project_root)})
        assert started["ok"] is True

        sent = await mcp_server.dispatch_tool("tg_send", {"text": "hello"})
        assert sent["ok"] is True
        assert "echo: hello" in sent["snapshot"]

        tapped = await mcp_server.dispatch_tool("tg_tap", {"label": "Button A"})
        assert tapped["ok"] is True
        assert "tap: btn_a" in tapped["snapshot"]

        logs = await mcp_server.dispatch_tool("tg_logs", {"tail": 10})
        assert logs["ok"] is True
    finally:
        await mcp_server.dispatch_tool("tg_stop", {})


@pytest.mark.asyncio
async def test_dispatch_tool_restart_smoke(tmp_path):
    project_root = write_echo_bot_project(tmp_path)
    try:
        await mcp_server.dispatch_tool("tg_start", {"project_root": str(project_root)})
        restarted = await mcp_server.dispatch_tool("tg_restart", {"project_root": str(project_root)})
        assert restarted["ok"] is True
    finally:
        await mcp_server.dispatch_tool("tg_stop", {})


def test_tool_definitions_include_project_root_and_expected_tools():
    definitions = {tool["name"]: tool for tool in mcp_server.tool_definitions()}
    assert "tg_start" in definitions
    assert "tg_send_photo" in definitions
    assert "tg_restart" in definitions
    assert "project_root" in definitions["tg_start"]["schema"]["properties"]
    assert "project_root" in definitions["tg_restart"]["schema"]["properties"]


def test_create_server_smoke_when_mcp_installed():
    if not mcp_server._MCP_AVAILABLE:
        pytest.skip("mcp sdk is not installed")
    server = mcp_server.create_server()
    assert server is not None


def test_codex_plugin_manifest_and_mcp_config_exist():
    repo_root = Path(__file__).resolve().parents[1]
    plugin_manifest = repo_root / ".codex-plugin" / "plugin.json"
    mcp_config = repo_root / ".mcp.json"
    readme = repo_root / "README.md"
    skills = [repo_root / "skills" / "setup" / "SKILL.md", repo_root / "skills" / "test" / "SKILL.md"]
    removed_vendor_name = "cl" + "aude"

    plugin = json.loads(plugin_manifest.read_text())
    config = json.loads(mcp_config.read_text())

    assert plugin["name"] == "tgmock"
    assert plugin["mcpServers"] == "./.mcp.json"
    assert plugin["skills"] == "./skills/"
    assert removed_vendor_name not in json.dumps(plugin).lower()

    assert "tgmock" in config["mcpServers"]
    assert config["mcpServers"]["tgmock"]["args"] == ["-m", "tgmock.mcp_server"]

    assert removed_vendor_name not in readme.read_text().lower()
    for skill in skills:
        assert removed_vendor_name not in skill.read_text().lower()
