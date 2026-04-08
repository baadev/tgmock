"""
Fake Telegram Bot API server for end-to-end bot testing.

Runs as a local aiohttp server. The bot points at it via BOT_API_BASE env var.

Fake Telegram API endpoints (aiogram / python-telegram-bot / etc. poll these):
  POST /bot{token}/getUpdates
  POST /bot{token}/sendMessage
  POST /bot{token}/editMessageText
  POST /bot{token}/answerCallbackQuery
  POST /bot{token}/sendChatAction
  POST /bot{token}/getMe
  POST /bot{token}/getFile
  POST /bot{token}/deleteMessage
  POST /bot{token}/editMessageReplyMarkup
  POST /bot{token}/sendPhoto
  POST /bot{token}/sendDocument
  POST /bot{token}/sendVoice
  POST /bot{token}/sendAudio
  POST /bot{token}/sendVideo
  POST /bot{token}/forwardMessage
  POST /bot{token}/copyMessage
  POST /bot{token}/sendLocation
  POST /bot{token}/sendContact
  POST /bot{token}/sendPoll
  POST /bot{token}/stopPoll
  POST /bot{token}/sendDice
  POST /bot{token}/pinChatMessage
  POST /bot{token}/unpinChatMessage
  POST /bot{token}/setMyCommands
  POST /bot{token}/getMyCommands
  POST /bot{token}/setWebhook
  POST /bot{token}/deleteWebhook
  GET  /file/bot{token}/{path}

Test control endpoints:
  POST   /test/send              {"text": "...", "user_id": 123}
  POST   /test/send-photo        {"user_id": 123, "caption": "...", "content": "..."}
  POST   /test/callback          {"data": "...", "user_id": 123, "message_id": 1}
  GET    /test/responses         → list of captured bot messages (optionally ?user_id=X)
  DELETE /test/responses         → clear captured list (optionally ?user_id=X)
  POST   /test/event             {"user_id": 123, "type": "tool_call", "data": {...}}
  GET    /test/events            → list of custom events (?user_id=X[&type=tool_call])
  DELETE /test/events            → clear events (?user_id=X)
  POST   /test/register-reset    {"url": "http://bot/internal/reset"}
  POST   /test/reset-user        clear server state for user, call registered reset hook
  GET    /test/wait-response     event-driven wait until bot settles
  GET    /test/users             list active user IDs
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from pathlib import PurePosixPath
from aiohttp import web

log = logging.getLogger(__name__)

TEST_USER = {
    "id": 111,
    "is_bot": False,
    "first_name": "TestUser",
    "username": "testuser",
    "language_code": "ru",
}


def _normalize_reply_markup(value):
    if value in (None, ""):
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


async def read_telegram_request(request: web.Request) -> dict:
    if request.content_type == "application/json":
        if request.content_length == 0:
            data = {}
        else:
            data = await request.json()
            if data is None:
                data = {}
            elif not isinstance(data, dict):
                raise web.HTTPBadRequest(text="Telegram JSON request body must be an object")
    else:
        data = dict((await request.post()).items())

    if "reply_markup" in data:
        data["reply_markup"] = _normalize_reply_markup(data.get("reply_markup"))
    return data


class TelegramMockServer:
    def __init__(self, token: str, port: int = 8999):
        self.token = token
        self.port = port
        self._update_id = 1
        self._msg_id = 1
        # All updates ever created; getUpdates filters by offset
        self._updates: list[dict] = []
        self._new_update = asyncio.Event()
        # All sendMessage / editMessageText calls the bot made
        self._responses: dict[int, list[dict]] = {}
        self._response_seq: dict[int, int] = {}
        self._last_response_at: dict[int, float] = {}
        self._response_event: asyncio.Event = asyncio.Event()
        # Custom events posted by the bot (tool calls, state changes, etc.)
        self._events: dict[int, list[dict]] = {}
        # Persistent message store: (chat_id, message_id) → latest message state.
        # Survives test_clear so callback queries can reference original messages.
        self._messages: dict[tuple[int, int], dict] = {}
        self._file_seq = 1
        self._files_by_id: dict[str, dict] = {}
        self._files_by_path: dict[str, dict] = {}
        # Optional reset hook: bot registers its callback URL here
        self._reset_url: str | None = None
        self._bot_activity_event = asyncio.Event()
        self._last_bot_activity_at = 0.0
        self._last_bot_activity_path: str | None = None

    # ── helpers ───────────────────────────────────────────────────────────────

    def _next_update_id(self) -> int:
        uid = self._update_id
        self._update_id += 1
        return uid

    def _next_msg_id(self) -> int:
        mid = self._msg_id
        self._msg_id += 1
        return mid

    def _next_file_id(self) -> str:
        file_id = f"mock_file_{self._file_seq}"
        self._file_seq += 1
        return file_id

    def _fake_message(self, text: str, user_id: int, msg_id: int | None = None) -> dict:
        mid = msg_id or self._next_msg_id()
        msg: dict = {
            "message_id": mid,
            "from": {**TEST_USER, "id": user_id},
            "chat": {"id": user_id, "type": "private"},
            "date": int(time.time()),
            "text": text,
        }
        # Add bot_command entity for /commands so bot frameworks can detect them
        if text.startswith("/"):
            cmd = text.split()[0] if text else text
            msg["entities"] = [{"type": "bot_command", "offset": 0, "length": len(cmd)}]
        return msg

    def _push_update(self, update: dict):
        self._updates.append(update)
        self._new_update.set()

    def _register_file(
        self,
        *,
        user_id: int | None,
        content: bytes,
        file_name: str,
        file_path: str | None = None,
        file_id: str | None = None,
        content_type: str = "application/octet-stream",
    ) -> dict:
        resolved_file_id = str(file_id or self._next_file_id())
        safe_name = PurePosixPath(file_name or f"{resolved_file_id}.bin").name
        resolved_file_path = file_path or f"photos/{resolved_file_id}/{safe_name}"
        entry = {
            "user_id": user_id,
            "file_id": resolved_file_id,
            "file_unique_id": f"unique_{resolved_file_id}",
            "file_size": len(content),
            "file_path": resolved_file_path,
            "content": content,
            "content_type": content_type,
        }
        self._files_by_id[resolved_file_id] = entry
        self._files_by_path[resolved_file_path] = entry
        return entry

    def _message_payload_from_record(
        self,
        stored: dict,
        *,
        chat_id: int,
        message_id: int,
    ) -> dict:
        payload: dict = {
            "message_id": message_id,
            "chat": {"id": chat_id, "type": "private"},
            "date": int(time.time()),
            "from": {"id": 999999, "is_bot": True, "first_name": "MockBot"},
        }
        for key in ("text", "caption", "reply_markup", "photo", "video", "audio", "voice", "document"):
            value = stored.get(key)
            if value not in (None, "", []):
                payload[key] = value
        return payload

    def _record_response(self, chat_id: int, record: dict):
        """Store a bot response and wake up any waiters."""
        self._responses.setdefault(chat_id, []).append(record)
        self._response_seq[chat_id] = self._response_seq.get(chat_id, 0) + 1
        self._last_response_at[chat_id] = asyncio.get_event_loop().time()
        self._response_event.set()
        # Keep persistent message state for callback query lookups
        mid = record.get("message_id")
        if mid is not None:
            self._messages[(chat_id, mid)] = record

    def mark_bot_activity(self, path: str) -> None:
        self._last_bot_activity_at = asyncio.get_event_loop().time()
        self._last_bot_activity_path = path
        self._bot_activity_event.set()

    def get_bot_activity_since(self, since: float) -> str | None:
        if self._last_bot_activity_at > since:
            return self._last_bot_activity_path
        return None

    async def reset_state(self, user_id: int | None = None, *, call_hook: bool = False) -> None:
        """Clear accumulated state for one user or all users."""
        if user_id is not None:
            self._responses.pop(user_id, None)
            self._events.pop(user_id, None)
            self._response_seq.pop(user_id, None)
            self._last_response_at.pop(user_id, None)
            self._messages = {
                key: value
                for key, value in self._messages.items()
                if key[0] != user_id
            }
            retained_files = {
                file_id: value
                for file_id, value in self._files_by_id.items()
                if value.get("user_id") != user_id
            }
            self._files_by_id = retained_files
            self._files_by_path = {
                value["file_path"]: value
                for value in retained_files.values()
            }
        else:
            self._responses.clear()
            self._events.clear()
            self._response_seq.clear()
            self._last_response_at.clear()
            self._messages.clear()
            self._files_by_id.clear()
            self._files_by_path.clear()

        if call_hook and self._reset_url:
            import aiohttp as _aiohttp

            try:
                async with _aiohttp.ClientSession() as session:
                    await session.post(
                        self._reset_url,
                        json={"user_id": user_id},
                        timeout=_aiohttp.ClientTimeout(total=3.0),
                    )
            except Exception as exc:
                log.warning(f"[TGMOCK] reset hook call failed: {exc}")

    # ── Telegram API: getUpdates (long-poll) ──────────────────────────────────

    async def handle_get_updates(self, request: web.Request) -> web.Response:
        data = await read_telegram_request(request)
        raw_offset = data.get("offset")
        if raw_offset in (None, ""):
            raw_offset = request.rel_url.query.get("offset", 0)
        raw_timeout = data.get("timeout")
        if raw_timeout in (None, ""):
            raw_timeout = request.rel_url.query.get("timeout", 0)
        offset = int(raw_offset or 0)
        timeout = int(raw_timeout or 0)
        deadline = asyncio.get_event_loop().time() + min(timeout, 2)

        while True:
            pending = [u for u in self._updates if u["update_id"] >= offset]
            if pending:
                return web.json_response({"ok": True, "result": pending})

            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                return web.json_response({"ok": True, "result": []})

            self._new_update.clear()
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._new_update.wait()),
                    timeout=min(remaining, 0.3),
                )
            except asyncio.TimeoutError:
                pass

    # ── Telegram API: sendMessage ─────────────────────────────────────────────

    async def handle_send_message(self, request: web.Request) -> web.Response:
        data = await read_telegram_request(request)
        mid = self._next_msg_id()
        chat_id = int(data.get("chat_id", 0))
        record = {
            "method": "sendMessage",
            "chat_id": chat_id,
            "text": data.get("text", ""),
            "parse_mode": data.get("parse_mode"),
            "reply_markup": data.get("reply_markup"),
            "message_id": mid,
        }
        self._record_response(chat_id, record)
        log.info(f"[BOT→USER] {record['text'][:120]}")
        return web.json_response({
            "ok": True,
            "result": self._fake_message(data.get("text", ""), chat_id, mid),
        })

    # ── Telegram API: editMessageText ─────────────────────────────────────────

    async def handle_edit_message_text(self, request: web.Request) -> web.Response:
        data = await read_telegram_request(request)
        chat_id = int(data.get("chat_id", 0))
        msg_id = int(data.get("message_id", 0))
        record = {
            "method": "editMessageText",
            "chat_id": chat_id,
            "message_id": msg_id,
            "text": data.get("text", ""),
            "parse_mode": data.get("parse_mode"),
            "reply_markup": data.get("reply_markup"),
        }
        self._record_response(chat_id, record)
        log.info(f"[BOT→EDIT] {record['text'][:120]}")
        return web.json_response({
            "ok": True,
            "result": {
                "message_id": msg_id,
                "chat": {"id": chat_id, "type": "private"},
                "date": int(time.time()),
                "text": data.get("text", ""),
            },
        })

    # ── Telegram API: getMe ───────────────────────────────────────────────────

    async def handle_get_me(self, request: web.Request) -> web.Response:
        return web.json_response({
            "ok": True,
            "result": {
                "id": 999999,
                "is_bot": True,
                "first_name": "MockBot",
                "username": "mockbot",
            },
        })

    async def handle_get_file(self, request: web.Request) -> web.Response:
        data = await read_telegram_request(request)
        file_id = data.get("file_id")
        if file_id in (None, ""):
            raise web.HTTPBadRequest(text="file_id is required")

        file_info = self._files_by_id.get(str(file_id))
        if file_info is None:
            return web.json_response(
                {
                    "ok": False,
                    "error_code": 400,
                    "description": "Bad Request: file not found",
                }
            )

        return web.json_response(
            {
                "ok": True,
                "result": {
                    "file_id": file_info["file_id"],
                    "file_unique_id": file_info["file_unique_id"],
                    "file_size": file_info["file_size"],
                    "file_path": file_info["file_path"],
                },
            }
        )

    async def handle_download_file(self, request: web.Request) -> web.Response:
        file_path = request.match_info.get("file_path", "")
        file_info = self._files_by_path.get(file_path)
        if file_info is None:
            raise web.HTTPNotFound(text="file not found")
        return web.Response(
            body=file_info["content"],
            content_type=file_info.get("content_type", "application/octet-stream"),
        )

    # ── Telegram API: no-ops ──────────────────────────────────────────────────

    async def handle_answer_callback_query(self, request: web.Request) -> web.Response:
        await read_telegram_request(request)
        return web.json_response({"ok": True, "result": True})

    async def handle_send_chat_action(self, request: web.Request) -> web.Response:
        await read_telegram_request(request)
        return web.json_response({"ok": True, "result": True})

    async def handle_delete_message(self, request: web.Request) -> web.Response:
        await read_telegram_request(request)
        return web.json_response({"ok": True, "result": True})

    async def handle_edit_message_reply_markup(self, request: web.Request) -> web.Response:
        data = await read_telegram_request(request)
        chat_id = int(data.get("chat_id", 0))
        msg_id = int(data.get("message_id", 0))
        self._record_response(chat_id, {
            "method": "editMessageReplyMarkup",
            "chat_id": chat_id,
            "message_id": msg_id,
            "reply_markup": data.get("reply_markup"),
        })
        return web.json_response({
            "ok": True,
            "result": {
                "message_id": msg_id,
                "chat": {"id": chat_id, "type": "private"},
                "date": int(time.time()),
                "text": "",
            },
        })

    # ── Telegram API: media stubs (HIGH priority) ─────────────────────────────

    async def _handle_send_media(self, request: web.Request, method: str, media_key: str) -> web.Response:
        """Generic handler for sendPhoto, sendDocument, sendVoice, etc."""
        data = await read_telegram_request(request)
        chat_id = int(data.get("chat_id", 0))
        mid = self._next_msg_id()
        media_value = data.get(media_key)
        if isinstance(media_value, dict):
            media_payload = dict(media_value)
        elif media_value not in (None, ""):
            media_payload = {"file_id": str(media_value)}
        else:
            media_payload = {}
        media_payload.setdefault("file_id", f"mock_{media_key}_{mid}")
        record = {
            "method": method,
            "chat_id": chat_id,
            "message_id": mid,
            "caption": data.get("caption", ""),
            "reply_markup": data.get("reply_markup"),
            media_key: media_payload,
        }
        self._record_response(chat_id, record)
        return web.json_response({
            "ok": True,
            "result": {
                "message_id": mid,
                "chat": {"id": chat_id, "type": "private"},
                "date": int(time.time()),
                "caption": data.get("caption", ""),
                media_key: media_payload,
            },
        })

    async def handle_send_photo(self, request: web.Request) -> web.Response:
        return await self._handle_send_media(request, "sendPhoto", "photo")

    async def handle_send_document(self, request: web.Request) -> web.Response:
        return await self._handle_send_media(request, "sendDocument", "document")

    async def handle_send_voice(self, request: web.Request) -> web.Response:
        return await self._handle_send_media(request, "sendVoice", "voice")

    async def handle_send_audio(self, request: web.Request) -> web.Response:
        return await self._handle_send_media(request, "sendAudio", "audio")

    async def handle_send_video(self, request: web.Request) -> web.Response:
        return await self._handle_send_media(request, "sendVideo", "video")

    async def handle_forward_message(self, request: web.Request) -> web.Response:
        data = await read_telegram_request(request)
        chat_id = int(data.get("chat_id", 0))
        mid = self._next_msg_id()
        return web.json_response({"ok": True, "result": self._fake_message("", chat_id, mid)})

    async def handle_copy_message(self, request: web.Request) -> web.Response:
        data = await read_telegram_request(request)
        mid = self._next_msg_id()
        return web.json_response({"ok": True, "result": {"message_id": mid}})

    async def handle_send_location(self, request: web.Request) -> web.Response:
        data = await read_telegram_request(request)
        chat_id = int(data.get("chat_id", 0))
        mid = self._next_msg_id()
        return web.json_response({
            "ok": True,
            "result": {
                "message_id": mid,
                "chat": {"id": chat_id, "type": "private"},
                "date": int(time.time()),
                "location": {"latitude": 0.0, "longitude": 0.0},
            },
        })

    async def handle_send_contact(self, request: web.Request) -> web.Response:
        data = await read_telegram_request(request)
        chat_id = int(data.get("chat_id", 0))
        mid = self._next_msg_id()
        return web.json_response({"ok": True, "result": self._fake_message("", chat_id, mid)})

    async def handle_send_poll(self, request: web.Request) -> web.Response:
        data = await read_telegram_request(request)
        chat_id = int(data.get("chat_id", 0))
        mid = self._next_msg_id()
        return web.json_response({
            "ok": True,
            "result": {
                "message_id": mid,
                "chat": {"id": chat_id, "type": "private"},
                "date": int(time.time()),
                "poll": {"id": str(mid), "question": data.get("question", ""), "options": [], "is_closed": False},
            },
        })

    async def handle_stop_poll(self, request: web.Request) -> web.Response:
        await read_telegram_request(request)
        return web.json_response({"ok": True, "result": {"id": "0", "question": "", "options": [], "is_closed": True}})

    async def handle_send_dice(self, request: web.Request) -> web.Response:
        data = await read_telegram_request(request)
        chat_id = int(data.get("chat_id", 0))
        mid = self._next_msg_id()
        return web.json_response({
            "ok": True,
            "result": {
                "message_id": mid,
                "chat": {"id": chat_id, "type": "private"},
                "date": int(time.time()),
                "dice": {"emoji": "🎲", "value": 1},
            },
        })

    async def _noop(self, request: web.Request) -> web.Response:
        await read_telegram_request(request)
        return web.json_response({"ok": True, "result": True})

    # ── Test control: inject a user message ───────────────────────────────────

    async def test_send(self, request: web.Request) -> web.Response:
        """POST /test/send  {"text": "привет", "user_id": 111}"""
        data = await request.json()
        text = data.get("text", "")
        user_id = int(data.get("user_id", TEST_USER["id"]))
        msg_id = self._next_msg_id()
        update = {
            "update_id": self._next_update_id(),
            "message": self._fake_message(text, user_id, msg_id),
        }
        self._push_update(update)
        log.info(f"[USER→BOT] {text!r}")
        return web.json_response({
            "ok": True,
            "update_id": update["update_id"],
            "after_seq": self._response_seq.get(user_id, 0),
        })

    async def test_send_photo(self, request: web.Request) -> web.Response:
        """POST /test/send-photo  {"user_id": 111, "caption": "...", "content": "..."}"""
        data = await request.json()
        user_id = int(data.get("user_id", TEST_USER["id"]))
        caption = data.get("caption", "")
        file_name = str(data.get("file_name", "photo.jpg"))
        mime_type = str(data.get("mime_type", "image/jpeg"))
        raw_content = data.get("content")
        raw_content_b64 = data.get("content_b64")
        if raw_content_b64 not in (None, ""):
            content = base64.b64decode(raw_content_b64)
        elif raw_content not in (None, ""):
            if isinstance(raw_content, str):
                content = raw_content.encode("utf-8")
            else:
                content = json.dumps(raw_content, ensure_ascii=False).encode("utf-8")
        else:
            content = b"mock-photo-content"

        file_info = self._register_file(
            user_id=user_id,
            content=content,
            file_name=file_name,
            file_path=data.get("file_path"),
            file_id=data.get("file_id"),
            content_type=mime_type,
        )
        msg_id = self._next_msg_id()
        message = {
            "message_id": msg_id,
            "from": {**TEST_USER, "id": user_id},
            "chat": {"id": user_id, "type": "private"},
            "date": int(time.time()),
            "photo": [
                {
                    "file_id": file_info["file_id"],
                    "file_unique_id": file_info["file_unique_id"],
                    "file_size": file_info["file_size"],
                    "width": int(data.get("width", 640)),
                    "height": int(data.get("height", 640)),
                }
            ],
        }
        if caption:
            message["caption"] = caption

        update = {
            "update_id": self._next_update_id(),
            "message": message,
        }
        self._push_update(update)
        log.info(f"[USER→BOT] <photo> {caption!r}")
        return web.json_response(
            {
                "ok": True,
                "update_id": update["update_id"],
                "after_seq": self._response_seq.get(user_id, 0),
                "file": {
                    "file_id": file_info["file_id"],
                    "file_path": file_info["file_path"],
                },
            }
        )

    # ── Test control: inject a callback query (button click) ──────────────────

    async def test_callback(self, request: web.Request) -> web.Response:
        """POST /test/callback  {"data": "choice:yes", "user_id": 111, "message_id": 5}"""
        data = await request.json()
        user_id = int(data.get("user_id", TEST_USER["id"]))
        callback_data = data.get("data", "")
        message_id = int(data.get("message_id", 1))

        # Look up the original message from persistent store (survives test_clear)
        stored = self._messages.get((user_id, message_id), {})
        orig_text = stored.get("text", "")
        orig_markup = stored.get("reply_markup")

        cb_message = self._message_payload_from_record(
            stored,
            chat_id=user_id,
            message_id=message_id,
        )
        if "text" not in cb_message and orig_text:
            cb_message["text"] = orig_text
        if "reply_markup" not in cb_message and orig_markup:
            cb_message["reply_markup"] = orig_markup

        update = {
            "update_id": self._next_update_id(),
            "callback_query": {
                "id": str(self._next_update_id()),
                "from": {**TEST_USER, "id": user_id},
                "message": cb_message,
                "chat_instance": "mock",
                "data": callback_data,
            },
        }
        self._push_update(update)
        log.info(f"[USER→BUTTON] {callback_data!r}")
        return web.json_response({
            "ok": True,
            "update_id": update["update_id"],
            "after_seq": self._response_seq.get(user_id, 0),
        })

    # ── Test control: read captured responses ─────────────────────────────────

    async def test_responses(self, request: web.Request) -> web.Response:
        """GET /test/responses[?user_id=X]"""
        user_id = request.rel_url.query.get("user_id")
        if user_id is not None:
            return web.json_response(self._responses.get(int(user_id), []))
        all_msgs = [msg for msgs in self._responses.values() for msg in msgs]
        return web.json_response(all_msgs)

    async def test_clear(self, request: web.Request) -> web.Response:
        """DELETE /test/responses[?user_id=X]"""
        user_id = request.rel_url.query.get("user_id")
        if user_id is not None:
            self._responses.pop(int(user_id), None)
        else:
            self._responses.clear()
        return web.json_response({"ok": True})

    # ── Test control: custom event bus ────────────────────────────────────────

    async def test_post_event(self, request: web.Request) -> web.Response:
        """POST /test/event  {"user_id": 123, "type": "tool_call", "data": {...}}"""
        body = await request.json()
        uid = int(body["user_id"])
        entry = {
            "type": body["type"],
            "data": body.get("data", {}),
            "ts": asyncio.get_event_loop().time(),
        }
        self._events.setdefault(uid, []).append(entry)
        return web.json_response({"ok": True})

    async def test_get_events(self, request: web.Request) -> web.Response:
        """GET /test/events?user_id=X[&type=tool_call]"""
        uid = int(request.rel_url.query.get("user_id", 0))
        type_filter = request.rel_url.query.get("type")
        events = self._events.get(uid, [])
        if type_filter:
            events = [e for e in events if e["type"] == type_filter]
        return web.json_response(events)

    async def test_clear_events(self, request: web.Request) -> web.Response:
        """DELETE /test/events[?user_id=X]"""
        uid_str = request.rel_url.query.get("user_id")
        if uid_str is not None:
            self._events.pop(int(uid_str), None)
        else:
            self._events.clear()
        return web.json_response({"ok": True})

    # ── Test control: reset hook registration ────────────────────────────────

    async def test_register_reset(self, request: web.Request) -> web.Response:
        """POST /test/register-reset  {"url": "http://bot-host/internal/reset"}"""
        body = await request.json()
        self._reset_url = body["url"]
        log.info(f"[TGMOCK] reset hook registered: {self._reset_url}")
        return web.json_response({"ok": True})

    async def test_reset_user(self, request: web.Request) -> web.Response:
        """POST /test/reset-user?user_id=X
        Clears server-side state for this user, then calls the bot's reset hook if registered.
        """
        uid_str = request.rel_url.query.get("user_id")
        uid = int(uid_str) if uid_str else None
        await self.reset_state(user_id=uid, call_hook=True)
        return web.json_response({"ok": True})

    async def test_reset_all(self, request: web.Request) -> web.Response:
        await self.reset_state(call_hook=True)
        return web.json_response({"ok": True})

    # ── Test control: list active users ──────────────────────────────────────

    async def test_users(self, request: web.Request) -> web.Response:
        """GET /test/users — list all user IDs with response count and last message preview."""
        result = []
        for uid, msgs in self._responses.items():
            last_text = ""
            if msgs:
                last_text = (msgs[-1].get("text") or msgs[-1].get("caption") or "")[:60]
            result.append({
                "user_id": uid,
                "response_count": len(msgs),
                "last_message": last_text,
            })
        return web.json_response(result)

    # ── Test control: event-driven wait ───────────────────────────────────────

    async def test_wait_response(self, request: web.Request) -> web.Response:
        """GET /test/wait-response?user_id=X&after_seq=N&settle_ms=400&timeout=30
        Blocks until the bot has sent at least one response after after_seq for this user,
        then waits for a settle period with no new responses.
        """
        user_id = int(request.rel_url.query.get("user_id", 0))
        after_seq = int(request.rel_url.query.get("after_seq", 0))
        settle_ms = float(request.rel_url.query.get("settle_ms", 400)) / 1000
        timeout = float(request.rel_url.query.get("timeout", 30))

        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout

        # Phase 1: wait for at least one new response after after_seq
        while self._response_seq.get(user_id, 0) <= after_seq:
            if loop.time() >= deadline:
                return web.json_response({"ok": False, "reason": "timeout"})
            self._response_event.clear()
            if self._response_seq.get(user_id, 0) > after_seq:
                break
            try:
                remaining = deadline - loop.time()
                await asyncio.wait_for(
                    asyncio.shield(self._response_event.wait()),
                    timeout=min(remaining, 0.3),
                )
            except asyncio.TimeoutError:
                pass

        # Phase 2: settle — wait until no new response for settle_ms
        while True:
            last = self._last_response_at.get(user_id, 0.0)
            since = loop.time() - last
            if since >= settle_ms:
                break
            if loop.time() >= deadline:
                break
            await asyncio.sleep(min(settle_ms - since + 0.01, 0.1))

        return web.json_response({"ok": True})

    # ── server setup ──────────────────────────────────────────────────────────

    def build_app(self) -> web.Application:
        @web.middleware
        async def _track_bot_activity(request: web.Request, handler):
            if request.path.startswith("/bot"):
                self.mark_bot_activity(request.path)
            return await handler(request)

        app = web.Application(middlewares=[_track_bot_activity])

        # Telegram Bot API endpoints — {token} wildcard accepts any bot token
        app.router.add_post("/bot{token}/getUpdates", self.handle_get_updates)
        app.router.add_post("/bot{token}/sendMessage", self.handle_send_message)
        app.router.add_post("/bot{token}/editMessageText", self.handle_edit_message_text)
        app.router.add_post("/bot{token}/getMe", self.handle_get_me)
        app.router.add_post("/bot{token}/getFile", self.handle_get_file)
        app.router.add_post("/bot{token}/answerCallbackQuery", self.handle_answer_callback_query)
        app.router.add_post("/bot{token}/sendChatAction", self.handle_send_chat_action)
        app.router.add_post("/bot{token}/deleteMessage", self.handle_delete_message)
        app.router.add_post("/bot{token}/editMessageReplyMarkup", self.handle_edit_message_reply_markup)
        # Media
        app.router.add_post("/bot{token}/sendPhoto", self.handle_send_photo)
        app.router.add_post("/bot{token}/sendDocument", self.handle_send_document)
        app.router.add_post("/bot{token}/sendVoice", self.handle_send_voice)
        app.router.add_post("/bot{token}/sendAudio", self.handle_send_audio)
        app.router.add_post("/bot{token}/sendVideo", self.handle_send_video)
        app.router.add_post("/bot{token}/forwardMessage", self.handle_forward_message)
        app.router.add_post("/bot{token}/copyMessage", self.handle_copy_message)
        app.router.add_post("/bot{token}/sendLocation", self.handle_send_location)
        app.router.add_post("/bot{token}/sendContact", self.handle_send_contact)
        app.router.add_post("/bot{token}/sendPoll", self.handle_send_poll)
        app.router.add_post("/bot{token}/stopPoll", self.handle_stop_poll)
        app.router.add_post("/bot{token}/sendDice", self.handle_send_dice)
        # No-ops
        app.router.add_post("/bot{token}/pinChatMessage", self._noop)
        app.router.add_post("/bot{token}/unpinChatMessage", self._noop)
        app.router.add_post("/bot{token}/setMyCommands", self._noop)
        app.router.add_post("/bot{token}/getMyCommands", self._noop)
        app.router.add_post("/bot{token}/setWebhook", self._noop)
        app.router.add_post("/bot{token}/deleteWebhook", self._noop)
        app.router.add_get("/file/bot{token}/{file_path:.*}", self.handle_download_file)

        # Test control endpoints
        app.router.add_post("/test/send", self.test_send)
        app.router.add_post("/test/send-photo", self.test_send_photo)
        app.router.add_post("/test/callback", self.test_callback)
        app.router.add_get("/test/responses", self.test_responses)
        app.router.add_delete("/test/responses", self.test_clear)
        app.router.add_post("/test/event", self.test_post_event)
        app.router.add_get("/test/events", self.test_get_events)
        app.router.add_delete("/test/events", self.test_clear_events)
        app.router.add_post("/test/register-reset", self.test_register_reset)
        app.router.add_post("/test/reset-user", self.test_reset_user)
        app.router.add_post("/test/reset-all", self.test_reset_all)
        app.router.add_get("/test/wait-response", self.test_wait_response)
        app.router.add_get("/test/users", self.test_users)
        return app

    async def start(self):
        app = self.build_app()
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "localhost", self.port)
        await site.start()
        log.info(f"Telegram mock server running on http://localhost:{self.port}")
        return runner
