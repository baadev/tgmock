---
name: tgmock:setup
description: Set up tgmock for a Telegram bot project in Codex. Use this skill whenever the user wants to configure, install, or debug tgmock setup for a Telegram bot, including cases like "set up bot testing", "wire tgmock into this project", "why does tg_start fail", or "make this bot testable in Codex".
---

You are configuring `tgmock` for a Telegram bot project so Codex can test it through the local MCP tools.

## Workflow

1. Inspect the project first.
   - Find the bot entrypoint if auto-detection might be ambiguous.
   - Check whether the bot already supports `BOT_API_BASE`.
   - Check whether the runtime is Python with `aiohttp` or `httpx`, because that enables auto-patch.

2. Configure tgmock in the target project.
   - Prefer zero-config startup first.
   - Only update the project's `.env` or `pyproject.toml` when auto-detection is wrong or the project needs a custom command.
   - Keep `project_root` explicit when later calling `tg_start`; do not assume the MCP server cwd matches the bot project.

3. Verify with the MCP tools.
   - Start with `tg_start(project_root=...)`.
   - Send a simple message with `tg_send`.
   - Inspect failures with `tg_logs`.
   - Stop the session with `tg_stop` after verification.

## Recommended configuration

Optional `.env`

```env
TGMOCK_BOT_COMMAND=python main.py
TGMOCK_READY_LOG=Bot starting
```

Optional `pyproject.toml`

```toml
[tool.tgmock]
bot_command = ["python", "main.py"]
ready_log = "Bot starting"
startup_timeout = 20
```

`TGMOCK_READY_LOG` is an override. If it is missing, `tgmock` waits for the first bot request to the mock API.

## Command handling rules

- `tgmock` does not use an implicit shell.
- Strings are parsed with `shlex.split`.
- If the project needs shell syntax, configure it explicitly, for example:

```toml
build_command = ["bash", "-lc", "go build -o /tmp/mybot ./cmd/server"]
```

## Auto-patch guidance

For Python bots launched through Python, `tgmock` can auto-patch `aiohttp` and `httpx` so no bot code changes are needed.

Disable auto-patch only when:

- the project is not Python
- the bot already has correct `BOT_API_BASE` wiring
- the user explicitly wants manual control

## Manual wiring guidance

If auto-patch is not applicable, make sure the bot reads `BOT_API_BASE` and points the Telegram API client at it.

## Common setup failures

- `Bot exited before ready`
  - wrong `TGMOCK_READY_LOG`
  - missing env vars
  - bad bot command

- `Timed out waiting for readiness`
  - the bot never reached `tgmock`
  - Node or Go bot is not wired to `BOT_API_BASE`
  - Python auto-patch does not apply to this HTTP client

- `404` from the mock server
  - bot is not using `BOT_API_BASE`
  - auto-patch is not active

- no responses after `tg_send`
  - bot never reached polling loop
  - wrong token/base URL wiring
  - startup log looked ready but actual loop failed immediately afterward

Always finish setup verification with:

1. `tg_start(project_root=...)`
2. `tg_send("hello")`
3. `tg_snapshot()`
4. `tg_stop()`
