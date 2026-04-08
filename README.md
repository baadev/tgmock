<div align="center">

# tgmock

### Test Telegram bots locally without hitting the real Telegram API

<p>
  <a href="./README.md"><strong>English</strong></a> · <a href="./README.ru.md">Русский</a>
</p>

<p>
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white">
  <img alt="Version" src="https://img.shields.io/badge/version-0.2.0-7B61FF">
  <img alt="Pytest plugin" src="https://img.shields.io/badge/pytest-plugin-0A9EDC?logo=pytest&logoColor=white">
  <img alt="MCP" src="https://img.shields.io/badge/Codex-MCP%20tools-111827">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-22C55E">
</p>

</div>

> **`tgmock`** is a local fake Telegram Bot API + bot runtime session manager + Codex MCP tool server + pytest plugin.

---

## Why tgmock

When your bot talks to the real Telegram API, tests are often slow and brittle.
`tgmock` starts a local HTTP mock of the Bot API so you can:

- send text and photo updates,
- press inline buttons,
- inspect bot responses and logs,
- collect custom events,
- run the same flow via Codex MCP tools or `pytest`.

## What’s included

- **Fake Telegram API server** (`TelegramMockServer`).
- **Session runtime** (`TgmockSession`) that runs the mock server + your bot subprocess.
- **MCP server** with tools like `tg_start`, `tg_send`, `tg_tap`, `tg_snapshot`, `tg_logs`, `tg_stop`.
- **Pytest plugin** with fixtures: `tg_runtime`, `tg_server`, `tg_bot`, `tg_client`, `tg_client_factory`.
- **CLI**:
  - `tgmock serve` — run the mock server only,
  - `tgmock mcp` — run the MCP server.

## Auto-detection support

`tgmock` can auto-detect bot startup commands for:

- **Python** (e.g. `bot.py`, `main.py`, package `__main__`),
- **Node.js** (`package.json` scripts `start`/`dev`, `main`, common entry files),
- **Go** (`main.go`, `cmd/*/main.go`, with pre-start build command).

If detection is wrong, set the command explicitly.

---

## Quick start

### 1) Install

```bash
pip install "tgmock[mcp]"
```

### 2) Connect to Codex

**Option A (recommended):** register this repository as a local Codex plugin.

```bash
python3 scripts/register_codex_plugin.py
```

**Option B:** register MCP manually.

```bash
codex mcp add tgmock -- python3 -m tgmock.mcp_server
```

### 3) Run a test session in Codex

Minimal flow:

1. `tg_start(project_root="/path/to/your-bot")`
2. `tg_send(text="/start")`
3. `tg_snapshot()` / `tg_logs()`
4. `tg_stop()`

> `project_root` must point to your **bot repository**, not this `tgmock` repository.

---

## How it works (short version)

1. `tgmock` loads config.
2. Starts local mock Telegram API (`http://localhost:<port>`).
3. Starts your bot as a subprocess.
4. Waits until ready:
   - by `ready_log`, or
   - by first bot request to mock API.
5. MCP/pytest inject updates and assert outputs.

---

## Configuration

Configuration priority (highest to lowest):

1. `TGMOCK_*` environment variables,
2. `TGMOCK_*` keys from `.env`,
3. `[tool.tgmock]` in `pyproject.toml`,
4. built-in defaults.

Example:

```toml
[tool.tgmock]
# bot_command = ["python", "main.py"]
# build_command = ["python", "-m", "compileall", "."]
# port = 8999
# token = "test:token"
# ready_log = "bot starting"
# startup_timeout = 15
# default_timeout = 25
# settle_ms = 400
# auto_patch = true
# env_file = ".env"

# [tool.tgmock.env]
# DATABASE_URL = "postgres://..."
```

### Python auto-patch

For Python commands, `tgmock` can auto-patch HTTP clients so Telegram API calls are redirected to the local mock server. In many projects this works without bot code changes.

---

## pytest example

```python
import pytest

@pytest.mark.tgmock
async def test_start_flow(tg_client):
    resp = await tg_client.send("/start")
    assert "start" in resp.text.lower()
```

Useful client methods:

- `send(text)`
- `send_photo(...)`
- `tap(label_or_data, prev=None)`
- `responses()`
- `events(type=None)`
- `reset()`

---

## Core MCP tools

- `tg_start` — start mock server + bot process,
- `tg_send` / `tg_send_photo` — inject updates,
- `tg_tap` — click inline keyboard buttons,
- `tg_snapshot` — conversation snapshot,
- `tg_events` — custom emitted events,
- `tg_logs` — bot log tail,
- `tg_restart` — restart bot process,
- `tg_stop` — stop current session.

---

## CLI

```bash
# run only mock Telegram Bot API
tgmock serve --port 8999 --token test:token

# run MCP server
tgmock mcp
```

---

## Troubleshooting

- If the bot fails to start, check `tg_logs` first.
- For Node/Go bots, ensure your bot supports custom `BOT_API_BASE`.
- If auto-detection fails, set `TGMOCK_BOT_COMMAND` or `[tool.tgmock].bot_command` explicitly.

---

## Repository layout

- `tgmock/` — runtime, server, MCP, pytest plugin, client.
- `scripts/register_codex_plugin.py` — local Codex plugin registration.
- `skills/` — Codex skill files.
- `tests/` — project test suite.

---

## License

MIT.
