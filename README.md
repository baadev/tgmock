# tgmock

Telegram bot testing for OpenAI Codex: fake Telegram Bot API server, pytest fixtures, and Codex MCP tools.

Works with any bot framework that talks to the Telegram Bot API, including aiogram, python-telegram-bot, Telegraf, and go-telegram-bot-api.

## What is this

`tgmock` helps you test a Telegram bot locally without real Telegram.

Instead of sending requests to the real Telegram Bot API, your bot talks to a local fake server. Codex can then:

- send messages to the bot
- press inline buttons
- read the bot's replies
- inspect logs
- verify side effects through structured events

In most Python projects this works with little or no bot code changes, because `tgmock` can automatically redirect `aiohttp` and `httpx` traffic to the local mock server.

## How it works

The flow is simple:

1. You tell `tgmock` how to start your bot.
2. `tgmock` starts a fake Telegram API on your machine.
3. Your bot connects to that fake API instead of real Telegram.
4. Codex uses `tg_*` tools like `tg_send` and `tg_tap` to simulate users.
5. You inspect the responses and logs until the flow is correct.

## Quick start

If you are new to the project, start with this section and ignore the rest for now.

### First understand the two repositories

During setup you usually work in **two different places**:

#### Repository 1: `tgmock`

This repository contains the tool itself:

- the fake Telegram API server
- the MCP server for Codex
- the skills and plugin manifest
- the pytest plugin

In this repository you usually do things like:

- install `tgmock`
- connect `tgmock` to Codex
- improve or debug `tgmock` itself

#### Repository 2: your bot project

This is the repository of the Telegram bot you want to test.

In the bot project you usually do things like:

- add `TGMOCK_BOT_COMMAND`
- add `TGMOCK_READY_LOG`
- optionally wire `BOT_API_BASE` if auto-patch is not enough
- ask Codex to start tests with `project_root` pointing to that bot project

Short version:

- install and maintain the tool here, in `tgmock`
- configure and test the actual bot in the bot repository

### 1. In the `tgmock` repository: install tgmock

```bash
pip install "tgmock[mcp]"
```

### 2. In the `tgmock` repository: connect tgmock to Codex

Manual MCP registration:

```bash
codex mcp add tgmock -- python3 -m tgmock.mcp_server
```

This repository also already contains a local Codex plugin manifest:

- `.codex-plugin/plugin.json`
- `.mcp.json`
- `skills/`

### 3. In the bot project: add minimal config

Now switch to the repository of the bot you want to test.

Create or update `.env` in the bot project:

```env
TGMOCK_BOT_COMMAND=python main.py
TGMOCK_READY_LOG=Bot starting
```

You only need:

- `TGMOCK_BOT_COMMAND`: how to start the bot
- `TGMOCK_READY_LOG`: a line from bot logs that means "the bot is ready"

If your bot prints something else on startup, use that text instead of `Bot starting`.

### 4. In Codex: ask it to test the bot project

Typical flow:

1. Ask Codex to inspect the bot project and confirm the entrypoint plus ready log.
2. Ask it to call `tg_start(project_root="...")`.
3. Ask it to send `/start` and check the response.
4. Ask it to stop the session with `tg_stop()`.

Example:

```text
Use tgmock to test this Telegram bot.
Project root is /path/to/bot.
Start the bot, send /start, show me the snapshot, then stop the session.
```

Important: `project_root` here is the path to the **bot project**, not the path to the `tgmock` repository.

### 5. If the bot does not start

First check:

- is `TGMOCK_BOT_COMMAND` correct?
- does `TGMOCK_READY_LOG` match the real startup log?
- does the bot actually start if you run the command manually?

Then use:

- `tg_logs()` to read stdout/stderr
- `tg_restart()` after config changes

### Minimal mental model

- `tgmock` repository: install the tool and expose its MCP server to Codex
- bot repository: tell `tgmock` how to start the bot
- Codex session: run `tg_start(project_root="path-to-bot-repo")` and test the flow

## For most Python bots

If the bot uses `aiohttp` or `httpx`, `tgmock` usually works without changing bot code. Start with the minimal config above first. Only read the manual wiring section later if auto-patch is not enough.

## Repository layout

This repository is now Codex-first:

- local Codex plugin manifest in [`.codex-plugin/plugin.json`](./.codex-plugin/plugin.json)
- MCP server config in [`.mcp.json`](./.mcp.json)
- Codex-native skills in [`skills/`](./skills/)
- no legacy assistant-specific files, commands, or docs

## Install and connection details

### Python package

```bash
pip install "tgmock[mcp]"
```

### Codex local plugin

This repository already contains the files a local Codex plugin needs:

- `.codex-plugin/plugin.json`
- `.mcp.json`
- `skills/`

Use the repository as a local plugin in Codex, or connect the MCP server manually.

### Fallback: manual MCP registration

```bash
codex mcp add tgmock -- python3 -m tgmock.mcp_server
```

## Detailed behavior

`tgmock` starts a local HTTP server that mimics the Telegram Bot API. Your bot talks to that server instead of the real Telegram API. Tests and Codex tools can then:

- send user messages
- tap inline keyboard buttons
- inspect rendered conversation snapshots
- read bot logs
- collect structured side-effect events

For Python bots, `tgmock` can auto-patch `aiohttp` and `httpx` so the bot is redirected to the mock server without code changes.

## Project configuration

Configure the target bot in `.env` or `pyproject.toml`.

### `.env`

```env
TGMOCK_BOT_COMMAND=python main.py
TGMOCK_READY_LOG=Bot starting
```

Optional:

```env
TGMOCK_BUILD_COMMAND=python -m compileall .
TGMOCK_PORT=8999
TGMOCK_STARTUP_TIMEOUT=20
TGMOCK_AUTO_PATCH=true
```

### `pyproject.toml`

```toml
[tool.tgmock]
bot_command = ["python", "main.py"]
ready_log = "Bot starting"
port = 8999
startup_timeout = 20
default_timeout = 25
settle_ms = 400
auto_patch = true
```

Commands can be configured either as:

- strings, parsed with `shlex.split`
- arrays, used as exact argv

`tgmock` does **not** invoke a shell implicitly. If you really need shell syntax, pass it explicitly, for example:

```toml
build_command = ["bash", "-lc", "go build -o /tmp/mybot ./cmd/server"]
```

Config priority stays the same:

1. `TGMOCK_*` process environment variables
2. `TGMOCK_*` values from the project `.env`
3. `[tool.tgmock]` in `pyproject.toml`
4. built-in defaults

## Auto-patch vs manual wiring

### Auto-patch

Enabled by default for Python bots whose start command resolves to Python. `tgmock` injects a temporary `sitecustomize.py` and redirects requests from `api.telegram.org` to the mock server.

Supported clients:

- `aiohttp`
- `httpx`

Disable it with:

```env
TGMOCK_AUTO_PATCH=false
```

### Manual wiring

For non-Python bots, or when auto-patch is disabled, wire `BOT_API_BASE` into the bot yourself.

**aiogram 3.x**

```python
import os
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

api_base = os.environ.get("BOT_API_BASE")
if api_base:
    session = AiohttpSession(api=TelegramAPIServer.from_base(api_base))
    bot = Bot(token=config.bot_token, session=session)
else:
    bot = Bot(token=config.bot_token)
```

**python-telegram-bot**

```python
base_url = os.environ.get("BOT_API_BASE", "https://api.telegram.org/bot")
app = Application.builder().token(TOKEN).base_url(base_url).build()
```

**Telegraf**

```js
const bot = new Telegraf(token, {
  telegram: { apiRoot: process.env.BOT_API_BASE || "https://api.telegram.org" }
})
```

**go-telegram-bot-api**

```go
bot, _ := tgbotapi.NewBotAPIWithAPIEndpoint(token, os.Getenv("BOT_API_BASE")+"/bot%s/%s")
```

## Codex MCP tools

The MCP server exposes these tools:

| Tool | Purpose |
| --- | --- |
| `tg_start` | Start the fake Telegram API and the bot subprocess |
| `tg_send` | Send a text message as a test user |
| `tg_tap` | Tap an inline keyboard button by label |
| `tg_snapshot` | Read the current conversation snapshot |
| `tg_events` | Read structured side-effect events |
| `tg_logs` | Read the latest bot stdout/stderr lines |
| `tg_users` | List active mock users |
| `tg_reset` | Reset one user's responses, events, and bot-side state |
| `tg_restart` | Restart only the bot process |
| `tg_stop` | Stop the bot and mock server |

`tg_start` and `tg_restart` accept `project_root`, so Codex does not have to rely on the MCP server's current working directory.

## Typical Codex flow

1. Inspect the target project and confirm the bot entrypoint plus ready log.
2. Call `tg_start(project_root=...)`.
3. Exercise the bot with `tg_send`, `tg_tap`, `tg_snapshot`, `tg_events`, and `tg_logs`.
4. Call `tg_stop()` when done.

## pytest usage

The pytest plugin is still auto-registered via `pytest11`.

```python
async def test_start(tg_client):
    response = await tg_client.send("/start")
    assert "Welcome" in response.text
```

Available fixtures:

- `tg_runtime`
- `tg_server`
- `tg_bot`
- `tg_client`
- `tg_client_factory`

## Structured events

Bots can post structured test events instead of forcing assertions through UI text.

```python
import aiohttp
import os

async def post_event(event_type: str, data: dict):
    base = os.environ.get("BOT_API_BASE", "")
    if not base:
        return
    async with aiohttp.ClientSession() as session:
        await session.post(
            f"{base}/test/event",
            json={"user_id": 111, "type": event_type, "data": data},
        )
```

Then inspect them with `tg_events(type="tool_call")` or `client.events(type="tool_call")`.

## Debugging

- If the bot exits before readiness, `tg_start` returns the last captured log lines.
- Use `tg_logs()` to inspect stdout/stderr at any point.
- Use `tg_restart()` after code or env changes.
- Use `tg_reset(user_id=...)` to clear one test user's state without stopping the whole session.

## License

MIT
