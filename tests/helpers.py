from __future__ import annotations

import json
import sys
from pathlib import Path


BOT_SCRIPT = """\
import asyncio
import json
import os

import aiohttp

BASE = os.environ["BOT_API_BASE"].rstrip("/")
TOKEN = os.environ.get("BOT_TOKEN", "test:token")
READY_LOG = os.environ.get("TGMOCK_TEST_READY_LOG", "bot starting")


async def main() -> None:
    print(READY_LOG, flush=True)
    offset = 0
    async with aiohttp.ClientSession() as session:
        while True:
            async with session.post(
                f"{BASE}/bot{TOKEN}/getUpdates",
                data={"offset": offset, "timeout": 1},
            ) as response:
                payload = await response.json()

            for update in payload.get("result", []):
                offset = update["update_id"] + 1
                if "message" in update:
                    message = update["message"]
                    chat_id = message["chat"]["id"]
                    text = message.get("text", "")
                    await session.post(
                        f"{BASE}/bot{TOKEN}/sendMessage",
                        data={
                            "chat_id": chat_id,
                            "text": f"echo: {text}",
                            "reply_markup": json.dumps(
                                {
                                    "inline_keyboard": [[
                                        {"text": "Button A", "callback_data": "btn_a"},
                                        {"text": "Button B", "callback_data": "btn_b"},
                                    ]]
                                }
                            ),
                        },
                    )
                elif "callback_query" in update:
                    callback = update["callback_query"]
                    chat_id = callback["message"]["chat"]["id"]
                    await session.post(
                        f"{BASE}/bot{TOKEN}/sendMessage",
                        data={"chat_id": chat_id, "text": f"tap: {callback['data']}"},
                    )
                    await session.post(
                        f"{BASE}/bot{TOKEN}/answerCallbackQuery",
                        data={"callback_query_id": callback["id"]},
                    )

            await asyncio.sleep(0.05)


if __name__ == "__main__":
    asyncio.run(main())
"""


def write_echo_bot_project(tmp_path: Path, *, ready_log: str = "bot starting") -> Path:
    project_root = tmp_path / "bot-project"
    project_root.mkdir()
    (project_root / "bot.py").write_text(BOT_SCRIPT)
    (project_root / "pyproject.toml").write_text(
        "\n".join(
            [
                "[tool.tgmock]",
                f"bot_command = {json.dumps([sys.executable, 'bot.py'])}",
                f"ready_log = {json.dumps(ready_log)}",
                "startup_timeout = 5",
                "default_timeout = 5",
                "settle_ms = 50",
            ]
        )
        + "\n"
    )
    return project_root
