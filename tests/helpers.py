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


def write_echo_bot_project_without_config(tmp_path: Path) -> Path:
    project_root = tmp_path / "bot-project-auto"
    project_root.mkdir()
    (project_root / "bot.py").write_text(BOT_SCRIPT)
    venv_bin = project_root / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    wrapper = venv_bin / "python"
    wrapper.write_text(f"#!/bin/sh\nexec {sys.prefix}/bin/python \"$@\"\n")
    wrapper.chmod(0o755)
    return project_root


NODE_BOT_SCRIPT = """\
const sleep = require("node:timers/promises").setTimeout;

const base = (process.env.BOT_API_BASE || "").replace(/\\/$/, "");
const token = process.env.BOT_TOKEN || "test:token";

if (!base) {
  throw new Error("BOT_API_BASE is required");
}

async function api(method, data) {
  const response = await fetch(`${base}/bot${token}/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(data),
  });
  return await response.json();
}

async function main() {
  let offset = 0;
  while (true) {
    const payload = await api("getUpdates", { offset, timeout: 1 });
    for (const update of payload.result || []) {
      offset = update.update_id + 1;
      if (update.message) {
        await api("sendMessage", {
          chat_id: update.message.chat.id,
          text: `echo: ${update.message.text || ""}`,
          reply_markup: {
            inline_keyboard: [[
              { text: "Button A", callback_data: "btn_a" },
              { text: "Button B", callback_data: "btn_b" },
            ]],
          },
        });
      } else if (update.callback_query) {
        await api("sendMessage", {
          chat_id: update.callback_query.message.chat.id,
          text: `tap: ${update.callback_query.data}`,
        });
        await api("answerCallbackQuery", {
          callback_query_id: update.callback_query.id,
        });
      }
    }
    await sleep(50);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""


def write_node_echo_bot_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "node-bot-project"
    project_root.mkdir()
    (project_root / "bot.js").write_text(NODE_BOT_SCRIPT)
    (project_root / "package.json").write_text(
        json.dumps(
            {
                "name": "node-bot-project",
                "private": True,
                "scripts": {"start": "node bot.js"},
                "dependencies": {"telegraf": "^4.16.0"},
            },
            indent=2,
        )
        + "\n"
    )
    return project_root


GO_BOT_SCRIPT = """\
package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

type updatesResponse struct {
	Result []update `json:"result"`
}

type update struct {
	UpdateID      int            `json:"update_id"`
	Message       *message       `json:"message"`
	CallbackQuery *callbackQuery `json:"callback_query"`
}

type message struct {
	Text string `json:"text"`
	Chat struct {
		ID int `json:"id"`
	} `json:"chat"`
}

type callbackQuery struct {
	ID      string  `json:"id"`
	Data    string  `json:"data"`
	Message message `json:"message"`
}

func callAPI(client *http.Client, base string, token string, method string, values url.Values, out any) error {
	request, err := http.NewRequest("POST", fmt.Sprintf("%s/bot%s/%s", base, token, method), strings.NewReader(values.Encode()))
	if err != nil {
		return err
	}
	request.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	response, err := client.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if out == nil {
		_, _ = io.Copy(io.Discard, response.Body)
		return nil
	}
	return json.NewDecoder(response.Body).Decode(out)
}

func main() {
	base := strings.TrimRight(os.Getenv("BOT_API_BASE"), "/")
	if base == "" {
		panic("BOT_API_BASE is required")
	}
	token := os.Getenv("BOT_TOKEN")
	if token == "" {
		token = "test:token"
	}
	client := &http.Client{Timeout: 5 * time.Second}
	offset := 0
	for {
		values := url.Values{}
		values.Set("offset", fmt.Sprintf("%d", offset))
		values.Set("timeout", "1")
		var payload updatesResponse
		if err := callAPI(client, base, token, "getUpdates", values, &payload); err != nil {
			panic(err)
		}
		for _, item := range payload.Result {
			offset = item.UpdateID + 1
			if item.Message != nil {
				reply := url.Values{}
				reply.Set("chat_id", fmt.Sprintf("%d", item.Message.Chat.ID))
				reply.Set("text", fmt.Sprintf("echo: %s", item.Message.Text))
				reply.Set("reply_markup", `{"inline_keyboard":[[{"text":"Button A","callback_data":"btn_a"},{"text":"Button B","callback_data":"btn_b"}]]}`)
				if err := callAPI(client, base, token, "sendMessage", reply, nil); err != nil {
					panic(err)
				}
			}
			if item.CallbackQuery != nil {
				reply := url.Values{}
				reply.Set("chat_id", fmt.Sprintf("%d", item.CallbackQuery.Message.Chat.ID))
				reply.Set("text", fmt.Sprintf("tap: %s", item.CallbackQuery.Data))
				if err := callAPI(client, base, token, "sendMessage", reply, nil); err != nil {
					panic(err)
				}
				answer := url.Values{}
				answer.Set("callback_query_id", item.CallbackQuery.ID)
				if err := callAPI(client, base, token, "answerCallbackQuery", answer, nil); err != nil {
					panic(err)
				}
			}
		}
		time.Sleep(50 * time.Millisecond)
	}
}
"""


def write_go_echo_bot_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "go-bot-project"
    project_root.mkdir()
    (project_root / "go.mod").write_text("module example.com/go-bot-project\n\ngo 1.20\n")
    (project_root / "main.go").write_text(GO_BOT_SCRIPT)
    return project_root
