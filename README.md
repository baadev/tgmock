<div align="center">

# tgmock

### Тестируйте Telegram-бота локально без реального Telegram API

<p>
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white">
  <img alt="Version" src="https://img.shields.io/badge/version-0.2.0-7B61FF">
  <img alt="Pytest plugin" src="https://img.shields.io/badge/pytest-plugin-0A9EDC?logo=pytest&logoColor=white">
  <img alt="MCP" src="https://img.shields.io/badge/Codex-MCP%20tools-111827">
</p>

</div>

> **`tgmock`** — это локальный fake Telegram Bot API + runtime для запуска бота + MCP-инструменты для Codex + pytest-плагин.

---

## Почему это полезно

Когда бот общается с реальным Telegram API, тесты становятся хрупкими и медленными. `tgmock` поднимает локальный HTTP-сервер, который имитирует Bot API, и позволяет:

- отправлять боту сообщения и фото,
- нажимать inline-кнопки,
- читать ответы и логи,
- собирать кастомные события,
- запускать всё это из Codex (через MCP) или из `pytest`.

## Что внутри

- **Fake Telegram API server** (`TelegramMockServer`).
- **Session runtime** (`TgmockSession`), который поднимает сервер + процесс вашего бота.
- **MCP server** с инструментами `tg_start`, `tg_send`, `tg_tap`, `tg_snapshot`, `tg_logs`, `tg_stop` и др.
- **Pytest plugin** с фикстурами `tg_runtime`, `tg_server`, `tg_bot`, `tg_client`, `tg_client_factory`.
- **CLI**:
  - `tgmock serve` — поднять только mock-сервер,
  - `tgmock mcp` — поднять MCP-сервер.

## Поддерживаемые сценарии запуска бота

`tgmock` умеет авто-детектить команды запуска для:

- **Python** (например `bot.py`, `main.py`, `package.__main__`),
- **Node.js** (`package.json` scripts `start`/`dev`, `main`, популярные entrypoint-файлы),
- **Go** (`main.go`, `cmd/*/main.go`, с build-шагом перед стартом).

Если авто-детект не подходит, команду можно задать вручную.

---

## Быстрый старт

### 1) Установка

```bash
pip install "tgmock[mcp]"
```

### 2) Подключить к Codex

**Вариант A (рекомендуется):** зарегистрировать локальный плагин из этого репозитория.

```bash
python3 scripts/register_codex_plugin.py
```

**Вариант B:** добавить MCP вручную.

```bash
codex mcp add tgmock -- python3 -m tgmock.mcp_server
```

### 3) Запуск тестовой сессии в Codex

Минимальный flow:

1. `tg_start(project_root="/path/to/your-bot")`
2. `tg_send(text="/start")`
3. `tg_snapshot()` / `tg_logs()`
4. `tg_stop()`

> `project_root` должен указывать на **репозиторий бота**, а не на этот репозиторий.

---

## Как это работает (кратко)

1. `tgmock` читает конфиг.
2. Поднимает локальный mock Telegram API (`http://localhost:<port>`).
3. Запускает ваш бот как subprocess.
4. Ждёт готовности:
   - либо по `ready_log`,
   - либо по первому запросу бота в mock API.
5. Через MCP/pytest вы инжектируете апдейты и проверяете ответы.

---

## Конфигурация

Приоритет источников (сверху вниз):

1. `TGMOCK_*` переменные окружения,
2. `TGMOCK_*` из `.env`,
3. `[tool.tgmock]` в `pyproject.toml`,
4. значения по умолчанию.

Пример в `pyproject.toml`:

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

### Важно про Python auto-patch

Для Python-команд `tgmock` может автоматически пропатчить сетевые вызовы, чтобы трафик к Telegram API ушёл в локальный mock-сервер. Обычно это позволяет стартовать без изменения кода бота.

---

## Пример с pytest

```python
import pytest

@pytest.mark.tgmock
async def test_start_flow(tg_client):
    resp = await tg_client.send("/start")
    assert "start" in resp.text.lower()
```

Полезные методы клиента:

- `send(text)`
- `send_photo(...)`
- `tap(label_or_data, prev=None)`
- `responses()`
- `events(type=None)`
- `reset()`

---

## MCP инструменты (основные)

- `tg_start` — старт mock-сервера и бота,
- `tg_send` / `tg_send_photo` — отправка апдейтов,
- `tg_tap` — нажатие inline-кнопки,
- `tg_snapshot` — текущий снапшот диалога,
- `tg_events` — кастомные события,
- `tg_logs` — хвост логов,
- `tg_restart` — рестарт процесса бота,
- `tg_stop` — остановка сессии.

---

## CLI

```bash
# поднять только mock API сервер
tgmock serve --port 8999 --token test:token

# поднять MCP сервер
tgmock mcp
```

---

## Ограничения и советы

- Если бот не стартует, сначала смотрите `tg_logs`.
- Для Node/Go-проектов убедитесь, что бот может работать с кастомным `BOT_API_BASE`.
- Если авто-детект команды не сработал, задайте `TGMOCK_BOT_COMMAND` или `[tool.tgmock].bot_command` явно.

---

## Структура репозитория

- `tgmock/` — runtime, сервер, MCP, pytest plugin, клиент.
- `scripts/register_codex_plugin.py` — регистрация локального Codex-плагина.
- `skills/` — skill-файлы для Codex.
- `tests/` — тесты проекта.

---

## Лицензия

Добавьте секцию лицензии при публикации (например, MIT), если планируете открытый релиз.
