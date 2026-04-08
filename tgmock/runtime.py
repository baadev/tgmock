from __future__ import annotations

import asyncio
import collections
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from tgmock._autopatch import is_python_command, prepare_autopatch
from tgmock._commands import Command, command_preview, detect_command_runtime, normalize_command, prepend_pythonpath
from tgmock._config import TgmockConfig, load_config
from tgmock._discovery import discover_project
from tgmock.server import TelegramMockServer


class TgmockSession:
    """Shared runtime for the fake Telegram server and a bot subprocess."""

    def __init__(self) -> None:
        self.server_runner = None
        self.mock_server: TelegramMockServer | None = None
        self.bot_proc: subprocess.Popen[str] | None = None
        self.client_session = None
        self.base_url = "http://localhost:8999"
        self.project_root: Path | None = None
        self.config: TgmockConfig | None = None
        self.bot_logs: collections.deque[str] = collections.deque(maxlen=200)
        self.log_reader_task: asyncio.Task | None = None
        self.autopatch_tmpdir: str | None = None
        self._ready_log_event: asyncio.Event | None = None

    async def start(
        self,
        *,
        project_root: str | os.PathLike[str] | None = None,
        bot_command: Command | None = None,
        build_command: Command | None = None,
        port: int | None = None,
        ready_log: str | None = None,
        env: dict[str, str] | None = None,
        startup_timeout: float | None = None,
    ) -> dict[str, Any]:
        if self.is_running:
            await self.stop()

        root = self._resolve_project_root(project_root)
        cfg = load_config(root)
        if bot_command is not None:
            cfg.bot_command = bot_command
        if build_command is not None:
            cfg.build_command = build_command
        if port is not None:
            cfg.port = port
        if ready_log is not None:
            cfg.ready_log = ready_log
        if startup_timeout is not None:
            cfg.startup_timeout = startup_timeout
        discovery = discover_project(root)
        bot_command_missing = cfg.bot_command is None
        ready_log_missing = cfg.ready_log is None
        using_discovered_bot_command = False
        if cfg.bot_command is None:
            cfg.bot_command = discovery.bot_command
            using_discovered_bot_command = True
        if cfg.build_command is None and using_discovered_bot_command:
            cfg.build_command = discovery.build_command

        bot_argv = normalize_command(cfg.bot_command)
        if not bot_argv:
            raise ValueError(
                f"tgmock could not auto-detect how to start the bot in {root}. "
                "Set TGMOCK_BOT_COMMAND or [tool.tgmock].bot_command."
            )
        build_argv = normalize_command(cfg.build_command)

        self.project_root = root
        self.config = cfg
        self.base_url = f"http://localhost:{cfg.port}"
        self.bot_logs.clear()
        if bot_command_missing and discovery.reason:
            self._store_log(f"[tgmock] auto-detected bot command: {command_preview(cfg.bot_command)} ({discovery.reason})")
        elif cfg.bot_command is not None:
            self._store_log(f"[tgmock] bot command: {command_preview(cfg.bot_command)}")
        if cfg.build_command is not None:
            self._store_log(f"[tgmock] build command: {command_preview(cfg.build_command)}")
        if ready_log_missing:
            self._store_log("[tgmock] readiness: waiting for first bot request to tgmock")
        elif cfg.ready_log:
            self._store_log(f"[tgmock] readiness log: {cfg.ready_log}")

        bot_env = self._build_bot_env(root, cfg, env)

        if cfg.auto_patch and is_python_command(cfg.bot_command):
            self.autopatch_tmpdir, patch_env = prepare_autopatch(self.base_url)
            bot_env.update(patch_env)
            self._store_log("[tgmock] auto-patch enabled")

        if build_argv:
            await self._run_build(build_argv, bot_env, root)

        self.mock_server = TelegramMockServer(token=cfg.token, port=cfg.port)
        self.server_runner = await self.mock_server.start()

        activity_since = asyncio.get_event_loop().time()
        self.bot_proc = subprocess.Popen(
            bot_argv,
            cwd=str(root),
            env=bot_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        await self._start_log_reader(self.bot_proc, cfg.ready_log)

        t0 = asyncio.get_event_loop().time()
        try:
            await asyncio.wait_for(
                self._wait_ready(self.bot_proc, cfg.ready_log, cfg.startup_timeout, activity_since),
                timeout=cfg.startup_timeout,
            )
        except Exception as exc:
            last_logs = "\n".join(list(self.bot_logs)[-30:]) or "(no output captured)"
            await self.stop()
            raise RuntimeError(f"Bot failed to start: {exc}\n\nLast bot output:\n{last_logs}") from exc

        elapsed = asyncio.get_event_loop().time() - t0
        return {
            "ok": True,
            "pid": self.bot_proc.pid,
            "port": cfg.port,
            "base_url": self.base_url,
            "project_root": str(root),
            "bot_command": command_preview(cfg.bot_command),
            "message": f"Bot ready after {elapsed:.1f}s",
        }

    async def restart(
        self,
        *,
        project_root: str | os.PathLike[str] | None = None,
        bot_command: Command | None = None,
        env: dict[str, str] | None = None,
        startup_timeout: float | None = None,
    ) -> dict[str, Any]:
        if not self.mock_server or not self.server_runner or not self.config:
            return await self.start(
                project_root=project_root,
                bot_command=bot_command,
                env=env,
                startup_timeout=startup_timeout,
            )

        root = self._resolve_project_root(project_root, fallback=self.project_root)
        same_root = root == self.project_root
        cfg = load_config(root)
        if bot_command is not None:
            cfg.bot_command = bot_command
        elif same_root:
            cfg.bot_command = self.config.bot_command
        cfg.port = self.config.port
        cfg.token = self.config.token
        if same_root:
            cfg.ready_log = self.config.ready_log
            cfg.default_timeout = self.config.default_timeout
            cfg.settle_ms = self.config.settle_ms
            cfg.auto_patch = self.config.auto_patch
            cfg.env_file = self.config.env_file
            cfg.build_command = self.config.build_command
            cfg.env.update(self.config.env)
        if startup_timeout is not None:
            cfg.startup_timeout = startup_timeout
        elif same_root:
            cfg.startup_timeout = self.config.startup_timeout
        discovery = discover_project(root)
        using_discovered_bot_command = False
        if cfg.bot_command is None:
            cfg.bot_command = discovery.bot_command
            using_discovered_bot_command = True
        if cfg.build_command is None and using_discovered_bot_command:
            cfg.build_command = discovery.build_command

        await self._stop_bot()

        if self.mock_server:
            await self.mock_server.reset_state(call_hook=True)

        bot_env = self._build_bot_env(root, cfg, env)
        if self.autopatch_tmpdir and cfg.auto_patch and is_python_command(cfg.bot_command):
            bot_env["PYTHONPATH"] = prepend_pythonpath(bot_env, self.autopatch_tmpdir)

        bot_argv = normalize_command(cfg.bot_command)
        if not bot_argv:
            raise ValueError(
                f"tgmock could not auto-detect how to restart the bot in {root}. "
                "Set TGMOCK_BOT_COMMAND or [tool.tgmock].bot_command."
            )

        self.project_root = root
        self.config = cfg
        self.bot_logs.clear()
        self._store_log(f"[tgmock] bot command: {command_preview(cfg.bot_command)}")
        if cfg.build_command is not None:
            self._store_log(f"[tgmock] build command: {command_preview(cfg.build_command)}")
        if cfg.ready_log:
            self._store_log(f"[tgmock] readiness log: {cfg.ready_log}")
        else:
            self._store_log("[tgmock] readiness: waiting for first bot request to tgmock")
        activity_since = asyncio.get_event_loop().time()
        self.bot_proc = subprocess.Popen(
            bot_argv,
            cwd=str(root),
            env=bot_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        await self._start_log_reader(self.bot_proc, cfg.ready_log)
        try:
            await asyncio.wait_for(
                self._wait_ready(self.bot_proc, cfg.ready_log, cfg.startup_timeout, activity_since),
                timeout=cfg.startup_timeout,
            )
        except Exception as exc:
            last_logs = "\n".join(list(self.bot_logs)[-30:]) or "(no output captured)"
            await self._stop_bot()
            raise RuntimeError(f"Bot failed to restart: {exc}\n\nLast bot output:\n{last_logs}") from exc

        return {"ok": True, "pid": self.bot_proc.pid, "message": "Bot restarted"}

    async def stop(self, timeout: float = 5.0) -> dict[str, Any]:
        await self._stop_bot(timeout=timeout)

        if self.server_runner:
            await self.server_runner.cleanup()
            self.server_runner = None
            self.mock_server = None

        if self.client_session and not self.client_session.closed:
            await self.client_session.close()
            self.client_session = None

        if self.autopatch_tmpdir:
            shutil.rmtree(self.autopatch_tmpdir, ignore_errors=True)
            self.autopatch_tmpdir = None

        self.project_root = None
        self.config = None
        return {"ok": True, "message": "Server and bot stopped"}

    async def send(self, text: str, user_id: int = 111, timeout: float | None = None) -> dict[str, Any]:
        self._require_started()
        session = await self._get_http_session()
        settle_ms = self._settle_ms
        await self._clear_user_outputs(user_id)
        async with session.post(f"{self.base_url}/test/send", json={"text": text, "user_id": user_id}) as resp:
            data = await resp.json()
        after_seq = data.get("after_seq", 0)
        async with session.get(
            f"{self.base_url}/test/wait-response",
            params={
                "user_id": user_id,
                "after_seq": after_seq,
                "settle_ms": settle_ms,
                "timeout": timeout or self._default_timeout,
            },
        ) as resp:
            result = await resp.json()
        if not result.get("ok"):
            return {"ok": False, "reason": result.get("reason", "timeout"), "snapshot": "(timeout)"}
        messages = await self._get_responses(user_id)
        return {"ok": True, "snapshot": snapshot_text(messages), "messages": messages}

    async def tap(self, label: str, user_id: int = 111, timeout: float | None = None) -> dict[str, Any]:
        self._require_started()
        session = await self._get_http_session()
        messages = await self._get_responses(user_id)

        callback_data = None
        message_id = 1
        for msg in reversed(messages):
            keyboard = msg.get("reply_markup")
            if not keyboard or "inline_keyboard" not in keyboard:
                continue
            for row in keyboard["inline_keyboard"]:
                for button in row:
                    if label.lower() in button["text"].lower():
                        callback_data = button["callback_data"]
                        message_id = msg.get("message_id", 1)
                        break
                if callback_data:
                    break
            if callback_data:
                break

        if callback_data is None:
            all_buttons = [
                button["text"]
                for msg in messages
                for row in (msg.get("reply_markup") or {}).get("inline_keyboard", [])
                for button in row
            ]
            return {"ok": False, "error": f"Button {label!r} not found. Available: {all_buttons}"}

        await self._clear_user_outputs(user_id)
        async with session.post(
            f"{self.base_url}/test/callback",
            json={"data": callback_data, "user_id": user_id, "message_id": message_id},
        ) as resp:
            data = await resp.json()
        after_seq = data.get("after_seq", 0)
        async with session.get(
            f"{self.base_url}/test/wait-response",
            params={
                "user_id": user_id,
                "after_seq": after_seq,
                "settle_ms": self._settle_ms,
                "timeout": timeout or self._default_timeout,
            },
        ) as resp:
            result = await resp.json()
        if not result.get("ok"):
            return {"ok": False, "reason": result.get("reason", "timeout"), "snapshot": "(timeout)"}
        new_messages = await self._get_responses(user_id)
        return {"ok": True, "snapshot": snapshot_text(new_messages), "messages": new_messages}

    async def snapshot(self, user_id: int = 111) -> dict[str, Any]:
        self._require_started()
        messages = await self._get_responses(user_id)
        return {"ok": True, "snapshot": snapshot_text(messages), "messages": messages}

    async def events(self, user_id: int = 111, type: str | None = None) -> dict[str, Any]:
        self._require_started()
        session = await self._get_http_session()
        params: dict[str, Any] = {"user_id": user_id}
        if type is not None:
            params["type"] = type
        async with session.get(f"{self.base_url}/test/events", params=params) as resp:
            events = await resp.json()
        return {"ok": True, "events": events, "count": len(events)}

    async def reset(self, user_id: int = 111) -> dict[str, Any]:
        self._require_started()
        if self.mock_server:
            await self.mock_server.reset_state(user_id=user_id, call_hook=True)
            return {"ok": True}
        session = await self._get_http_session()
        async with session.post(f"{self.base_url}/test/reset-user", params={"user_id": user_id}) as resp:
            return await resp.json()

    async def users(self) -> dict[str, Any]:
        self._require_started()
        session = await self._get_http_session()
        async with session.get(f"{self.base_url}/test/users") as resp:
            users = await resp.json()
        return {"ok": True, "users": users}

    async def logs(self, tail: int = 50) -> dict[str, Any]:
        lines = list(self.bot_logs)[-tail:]
        return {"ok": True, "lines": lines, "count": len(lines)}

    @property
    def is_running(self) -> bool:
        return self.bot_proc is not None or self.server_runner is not None

    @property
    def _default_timeout(self) -> float:
        return self.config.default_timeout if self.config else 25.0

    @property
    def _settle_ms(self) -> int:
        return self.config.settle_ms if self.config else 400

    def _resolve_project_root(
        self,
        project_root: str | os.PathLike[str] | None,
        *,
        fallback: Path | None = None,
    ) -> Path:
        root = Path(project_root).expanduser() if project_root is not None else fallback or Path.cwd()
        root = root.resolve()
        if not root.exists():
            raise FileNotFoundError(f"project_root does not exist: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"project_root is not a directory: {root}")
        return root

    def _require_started(self) -> None:
        if not self.server_runner or not self.mock_server:
            raise RuntimeError("tgmock session is not running; call tg_start first")

    def _build_bot_env(
        self,
        project_root: Path,
        cfg: TgmockConfig,
        extra_env: dict[str, str] | None,
    ) -> dict[str, str]:
        bot_env = {**os.environ}
        env_path = project_root / cfg.env_file
        if env_path.exists():
            import dotenv

            bot_env.update({k: str(v) for k, v in dotenv.dotenv_values(env_path).items() if v is not None})
        bot_env["BOT_API_BASE"] = self.base_url
        bot_env["BOT_TOKEN"] = cfg.token
        bot_env.update(cfg.env)
        if extra_env:
            bot_env.update(extra_env)
        return bot_env

    async def _get_http_session(self):
        if self.client_session is None or self.client_session.closed:
            import aiohttp

            self.client_session = aiohttp.ClientSession()
        return self.client_session

    async def _get_responses(self, user_id: int) -> list[dict[str, Any]]:
        session = await self._get_http_session()
        async with session.get(f"{self.base_url}/test/responses", params={"user_id": user_id}) as resp:
            return await resp.json()

    async def _clear_user_outputs(self, user_id: int, *, clear_events: bool = False) -> None:
        session = await self._get_http_session()
        async with session.delete(f"{self.base_url}/test/responses", params={"user_id": user_id}):
            pass
        if clear_events:
            async with session.delete(f"{self.base_url}/test/events", params={"user_id": user_id}):
                pass

    async def _run_build(self, build_argv: list[str], bot_env: dict[str, str], project_root: Path) -> None:
        display = command_preview(build_argv)
        self._store_log(f"[tgmock] building: {display}")
        loop = asyncio.get_event_loop()
        completed = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                build_argv,
                cwd=str(project_root),
                env=bot_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            ),
        )
        output = completed.stdout or ""
        for line in output.splitlines():
            self._store_log(line)
        if completed.returncode != 0:
            raise RuntimeError(f"Build command failed (exit {completed.returncode}): {display}")

    async def _wait_ready(
        self,
        proc: subprocess.Popen[str],
        ready_log: str | None,
        timeout: float,
        activity_since: float,
    ) -> None:
        if timeout <= 0:
            raise RuntimeError("startup_timeout must be greater than zero")
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while True:
            if ready_log and self._ready_log_event and self._ready_log_event.is_set():
                await asyncio.sleep(0.1)
                if proc.poll() is not None:
                    raise RuntimeError("Bot exited after emitting the readiness log")
                return
            activity_path = self.mock_server.get_bot_activity_since(activity_since) if self.mock_server else None
            if activity_path:
                self._store_log(f"[tgmock] bot reached mock API: {activity_path}")
                await asyncio.sleep(0.1)
                if proc.poll() is not None:
                    raise RuntimeError("Bot exited after reaching the mock API")
                return
            if proc.poll() is not None:
                raise RuntimeError("Bot exited before ready")
            if loop.time() >= deadline:
                raise RuntimeError(self._readiness_timeout_message())
            await asyncio.sleep(0.05)

    async def _start_log_reader(self, proc: subprocess.Popen[str], ready_log: str | None) -> None:
        self._ready_log_event = asyncio.Event()

        async def _drain() -> None:
            loop = asyncio.get_event_loop()
            needle = ready_log.lower() if ready_log else None
            while proc.poll() is None:
                line = await loop.run_in_executor(None, proc.stdout.readline)
                if not line:
                    break
                self._store_log(line)
                sys.stderr.write(f"[BOT] {line}")
                if needle and needle in line.lower():
                    self._ready_log_event.set()

        if self.log_reader_task:
            self.log_reader_task.cancel()
            await asyncio.gather(self.log_reader_task, return_exceptions=True)
        self.log_reader_task = asyncio.create_task(_drain())

    async def _stop_bot(self, timeout: float = 5.0) -> None:
        if self.log_reader_task:
            self.log_reader_task.cancel()
            await asyncio.gather(self.log_reader_task, return_exceptions=True)
            self.log_reader_task = None
        self._ready_log_event = None

        if self.bot_proc:
            self.bot_proc.terminate()
            loop = asyncio.get_event_loop()
            try:
                await asyncio.wait_for(loop.run_in_executor(None, self.bot_proc.wait), timeout=timeout)
            except asyncio.TimeoutError:
                self.bot_proc.kill()
                await loop.run_in_executor(None, self.bot_proc.wait)
            self.bot_proc = None

    def _store_log(self, line: str) -> None:
        self.bot_logs.append(line.rstrip())

    def _readiness_timeout_message(self) -> str:
        runtime = detect_command_runtime(self.config.bot_command if self.config else None)
        if runtime == "python":
            return (
                "Timed out waiting for readiness. The bot never reached tgmock. "
                "If auto-patch does not apply, wire BOT_API_BASE manually."
            )
        if runtime in {"node", "go"}:
            return (
                "Timed out waiting for readiness. The bot never reached tgmock. "
                "Node and Go bots usually need explicit BOT_API_BASE wiring."
            )
        return "Timed out waiting for readiness. The bot never reached tgmock."


def snapshot_text(messages: list[dict[str, Any]]) -> str:
    if not messages:
        return "(no response)"
    media_labels = {
        "photo": "Photo",
        "video": "Video",
        "document": "Document",
        "audio": "Audio",
        "voice": "Voice",
    }
    parts: list[str] = []
    for index, message in enumerate(messages):
        if index > 0:
            parts.append("---")
        text = message.get("text", "")
        if not text:
            caption = message.get("caption", "")
            media_label = None
            for key, label in media_labels.items():
                if key in message:
                    media_label = label
                    break
            if media_label:
                text = f"[{media_label}] {caption}".strip()
            elif caption:
                text = caption
        if text:
            parts.append(f"[Bot] {text}")
        keyboard = message.get("reply_markup")
        if keyboard and "inline_keyboard" in keyboard:
            buttons = [button["text"] for row in keyboard["inline_keyboard"] for button in row]
            if buttons:
                parts.append(f"[Buttons: {' | '.join(buttons)}]")
    return "\n".join(parts)
