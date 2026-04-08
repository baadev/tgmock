"""
tgmock MCP server — lets Codex control a Telegram bot test session interactively.

Run manually:
    codex mcp add tgmock -- python3 -m tgmock.mcp_server
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from tgmock.runtime import TgmockSession

try:
    import mcp.server.stdio
    import mcp.types as types
    from mcp.server import Server

    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False


_SESSION = TgmockSession()


def tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "tg_start",
            "description": "Start the fake Telegram API server and bot subprocess.",
            "schema": {
                "type": "object",
                "properties": {
                    "project_root": {"type": "string", "description": "Project root containing the bot and tgmock config."},
                    "bot_command": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ],
                        "description": "Optional command to start the bot. When omitted, tgmock auto-detects common Python, Node, and Go entrypoints. Strings are parsed with shlex, not a shell.",
                    },
                    "build_command": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ],
                        "description": "Optional pre-start build command. Strings are parsed with shlex, not a shell.",
                    },
                    "port": {"type": "integer", "default": 8999},
                    "ready_log": {"type": "string", "description": "Optional substring in bot stdout that signals readiness. If omitted, tgmock waits for the first bot request to the mock API."},
                    "env": {"type": "object", "description": "Extra environment variables merged on top of config."},
                    "startup_timeout": {"type": "number", "default": 15.0},
                },
                "required": [],
            },
        },
        {
            "name": "tg_send",
            "description": "Send a text message as a test user and wait for the bot response.",
            "schema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "user_id": {"type": "integer", "default": 111},
                    "timeout": {"type": "number", "default": 25.0},
                },
                "required": ["text"],
            },
        },
        {
            "name": "tg_send_photo",
            "description": "Send a photo update as a test user and wait for the bot response.",
            "schema": {
                "type": "object",
                "properties": {
                    "caption": {"type": "string"},
                    "content": {"type": "string", "description": "Optional UTF-8 file contents for the mock photo download."},
                    "content_b64": {"type": "string", "description": "Optional base64-encoded file contents for binary payloads."},
                    "file_name": {"type": "string", "default": "photo.jpg"},
                    "mime_type": {"type": "string", "default": "image/jpeg"},
                    "user_id": {"type": "integer", "default": 111},
                    "timeout": {"type": "number", "default": 25.0},
                },
                "required": [],
            },
        },
        {
            "name": "tg_tap",
            "description": "Click an inline keyboard button by label (partial match).",
            "schema": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "user_id": {"type": "integer", "default": 111},
                    "timeout": {"type": "number", "default": 25.0},
                },
                "required": ["label"],
            },
        },
        {
            "name": "tg_snapshot",
            "description": "Get the current conversation snapshot for a user.",
            "schema": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer", "default": 111},
                },
                "required": [],
            },
        },
        {
            "name": "tg_events",
            "description": "Get custom events posted by the bot.",
            "schema": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer", "default": 111},
                    "type": {"type": "string"},
                },
                "required": [],
            },
        },
        {
            "name": "tg_logs",
            "description": "Get the last N lines from the bot log buffer.",
            "schema": {
                "type": "object",
                "properties": {
                    "tail": {"type": "integer", "default": 50},
                },
                "required": [],
            },
        },
        {
            "name": "tg_users",
            "description": "List active mock users and their last visible bot message.",
            "schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "tg_reset",
            "description": "Reset responses, events, and bot-side state for one test user.",
            "schema": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer", "default": 111},
                },
                "required": [],
            },
        },
        {
            "name": "tg_restart",
            "description": "Restart the bot process while keeping the mock server running.",
            "schema": {
                "type": "object",
                "properties": {
                    "project_root": {"type": "string"},
                    "bot_command": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ],
                    },
                    "env": {"type": "object"},
                    "startup_timeout": {"type": "number"},
                },
                "required": [],
            },
        },
        {
            "name": "tg_stop",
            "description": "Stop the bot subprocess and mock server.",
            "schema": {
                "type": "object",
                "properties": {
                    "timeout": {"type": "number", "default": 5.0},
                },
                "required": [],
            },
        },
    ]


async def dispatch_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    arguments = arguments or {}
    if name == "tg_start":
        return await _SESSION.start(**arguments)
    if name == "tg_send":
        return await _SESSION.send(**arguments)
    if name == "tg_send_photo":
        return await _SESSION.send_photo(**arguments)
    if name == "tg_tap":
        return await _SESSION.tap(**arguments)
    if name == "tg_snapshot":
        return await _SESSION.snapshot(**arguments)
    if name == "tg_events":
        return await _SESSION.events(**arguments)
    if name == "tg_logs":
        return await _SESSION.logs(**arguments)
    if name == "tg_users":
        return await _SESSION.users()
    if name == "tg_reset":
        return await _SESSION.reset(**arguments)
    if name == "tg_restart":
        return await _SESSION.restart(**arguments)
    if name == "tg_stop":
        return await _SESSION.stop(**arguments)
    return {"ok": False, "error": f"Unknown tool: {name}"}


def create_server() -> "Server":
    if not _MCP_AVAILABLE:
        raise ImportError("MCP SDK not installed. Run: pip install tgmock[mcp]")

    app = Server("tgmock")

    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=tool["name"],
                description=tool["description"],
                inputSchema=tool["schema"],
            )
            for tool in tool_definitions()
        ]

    @app.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
        result = await dispatch_tool(name, arguments)
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    return app


async def main() -> None:
    if not _MCP_AVAILABLE:
        print("ERROR: MCP SDK not installed. Run: pip install tgmock[mcp]", file=sys.stderr)
        sys.exit(1)

    app = create_server()
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
