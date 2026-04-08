<div align="center">

# tgmock

### Тестируйте Telegram-ботов локально без реального Telegram API

<p>
  <a href="./README.md">English</a> · <a href="./README.ru.md"><strong>Русский</strong></a>
</p>

<p>
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white">
  <img alt="Version" src="https://img.shields.io/badge/version-0.2.0-7B61FF">
  <img alt="Pytest plugin" src="https://img.shields.io/badge/pytest-plugin-0A9EDC?logo=pytest&logoColor=white">
  <img alt="MCP" src="https://img.shields.io/badge/Codex-MCP%20tools-111827">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-22C55E">
</p>

</div>

> **`tgmock`** — это локальный fake Telegram Bot API + runtime для запуска бота + MCP-инструменты для Codex + pytest-плагин.

---

## Почему tgmock

`tgmock` создан как инструмент для **автоматизации тестирования Telegram-ботов через Codex**.
Вместо проверки отдельных хендлеров вы можете попросить Codex прогнать реалистичные пользовательские сценарии end-to-end через локальный mock Bot API.

**Теперь вы можете попросить Codex протестировать реальные сценарии бота с точки зрения пользователя.**

С `tgmock` Codex (или `pytest`) может:

- отправлять боту текст и фото,
- нажимать inline-кнопки,
- смотреть ответы и логи,
- собирать кастомные события.

## Что входит в проект

- **Fake Telegram API server** (`TelegramMockServer`).
- **Session runtime** (`TgmockSession`) — поднимает mock-сервер и subprocess вашего бота.
- **MCP server** с инструментами `tg_start`, `tg_send`, `tg_tap`, `tg_snapshot`, `tg_logs`, `tg_stop`.
- **Pytest plugin** с фикстурами: `tg_runtime`, `tg_server`, `tg_bot`, `tg_client`, `tg_client_factory`.
- **CLI**:
  - `tgmock serve` — запуск только mock-сервера,
  - `tgmock mcp` — запуск MCP-сервера.

## Поддержка авто-детекта

`tgmock` умеет авто-определять команду запуска для:

- **Python** (например `bot.py`, `main.py`, package `__main__`),
- **Node.js** (`package.json` scripts `start`/`dev`, `main`, распространённые entrypoint-файлы),
- **Go** (`main.go`, `cmd/*/main.go`, с build-командой перед стартом).

Если авто-детект ошибся — задайте команду вручную.

---

## Быстрый старт

### 1) Установка

```bash
pip install "tgmock[mcp]"
```

### 2) Подключение к Codex

**Вариант A (рекомендуется):** зарегистрировать этот репозиторий как локальный Codex-плагин.

```bash
python3 scripts/register_codex_plugin.py
```

**Вариант B:** зарегистрировать MCP вручную.

```bash
codex mcp add tgmock -- python3 -m tgmock.mcp_server
```

### 3) Тестовая сессия в Codex

Минимальный flow:

1. `tg_start(project_root="/path/to/your-bot")`
2. `tg_send(text="/start")`
3. `tg_snapshot()` / `tg_logs()`
4. `tg_stop()`

> `project_root` должен указывать на **репозиторий бота**, а не на репозиторий `tgmock`.

---

## Как это работает (кратко)

1. `tgmock` читает конфиг.
2. Поднимает локальный mock Telegram API (`http://localhost:<port>`).
3. Запускает ваш бот как subprocess.
4. Ждёт готовности:
   - по `ready_log`, или
   - по первому запросу бота в mock API.
5. Через MCP/pytest инжектируются апдейты и проверяются ответы.

---

## Конфигурация

Приоритет конфигурации (сверху вниз):

1. переменные окружения `TGMOCK_*`,
2. ключи `TGMOCK_*` из `.env`,
3. секция `[tool.tgmock]` в `pyproject.toml`,
4. значения по умолчанию.

Пример:

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

Для Python-команд `tgmock` может автоматически пропатчить HTTP-вызовы так, чтобы обращения к Telegram API перенаправлялись в локальный mock-сервер. Во многих проектах это работает без изменений кода бота.

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

## Основные MCP инструменты

- `tg_start` — старт mock-сервера и процесса бота,
- `tg_send` / `tg_send_photo` — инжект апдейтов,
- `tg_tap` — нажатие inline-кнопок,
- `tg_snapshot` — снапшот диалога,
- `tg_events` — кастомные события,
- `tg_logs` — хвост логов,
- `tg_restart` — рестарт процесса бота,
- `tg_stop` — остановка сессии.

---

## CLI

```bash
# запуск только mock Telegram Bot API
tgmock serve --port 8999 --token test:token

# запуск MCP сервера
tgmock mcp
```

---

## Troubleshooting

- Если бот не стартует, сначала проверьте `tg_logs`.
- Для Node/Go-ботов убедитесь, что поддерживается кастомный `BOT_API_BASE`.
- Если авто-детект не сработал, задайте `TGMOCK_BOT_COMMAND` или `[tool.tgmock].bot_command` явно.

---

## Структура репозитория

- `tgmock/` — runtime, сервер, MCP, pytest plugin, клиент.
- `scripts/register_codex_plugin.py` — регистрация локального Codex-плагина.
- `skills/` — skill-файлы Codex.
- `tests/` — тесты проекта.

---

## Лицензия

MIT.
