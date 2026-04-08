"""
pytest plugin — provides tg_server, tg_bot, tg_client, tg_client_factory fixtures.

Auto-registered via entry_points["pytest11"] = "tgmock = tgmock.plugin".
"""
from __future__ import annotations

from collections.abc import AsyncGenerator, Callable, Coroutine
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from tgmock._config import TgmockConfig, load_config
from tgmock._user_id import next_user_id
from tgmock.client import BotTestClient
from tgmock.runtime import TgmockSession
from tgmock.server import TelegramMockServer


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "tgmock: marks tests that use the tgmock bot fixtures")
    try:
        if not config.option.__dict__.get("asyncio_mode"):
            config.option.asyncio_mode = "auto"
    except AttributeError:
        pass


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("tgmock")
    group.addoption("--tgmock-port", default=None, type=int, help="Override [tool.tgmock] port")
    group.addoption("--tgmock-command", default=None, help="Override [tool.tgmock] bot_command")


@pytest.fixture(scope="session")
def tgmock_config(request: pytest.FixtureRequest) -> TgmockConfig:
    cfg = load_config(Path(request.config.rootdir))
    if (port := request.config.getoption("--tgmock-port", default=None)) is not None:
        cfg.port = port
    if (command := request.config.getoption("--tgmock-command", default=None)) is not None:
        cfg.bot_command = command
    return cfg


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def tg_runtime(tgmock_config: TgmockConfig, request: pytest.FixtureRequest) -> AsyncGenerator[TgmockSession, None]:
    session = TgmockSession()
    await session.start(
        project_root=str(request.config.rootdir),
        bot_command=tgmock_config.bot_command,
        build_command=tgmock_config.build_command,
        port=tgmock_config.port,
        ready_log=tgmock_config.ready_log,
        startup_timeout=tgmock_config.startup_timeout,
    )
    try:
        yield session
    finally:
        await session.stop()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def tg_server(tg_runtime: TgmockSession) -> AsyncGenerator[TelegramMockServer, None]:
    yield tg_runtime.mock_server


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def tg_bot(tg_runtime: TgmockSession) -> AsyncGenerator[object, None]:
    yield tg_runtime.bot_proc


@pytest_asyncio.fixture(scope="function")
async def tg_client(
    tg_runtime: TgmockSession,
    tgmock_config: TgmockConfig,
) -> AsyncGenerator[BotTestClient, None]:
    uid = next_user_id()
    client = BotTestClient(
        base_url=tg_runtime.base_url,
        user_id=uid,
        default_timeout=tgmock_config.default_timeout,
    )
    await client.start()
    await client.clear()
    try:
        yield client
    finally:
        await client.clear()
        await client.stop()


@pytest_asyncio.fixture(scope="function")
async def tg_client_factory(
    tg_runtime: TgmockSession,
    tgmock_config: TgmockConfig,
) -> AsyncGenerator[Callable[[], Coroutine[Any, Any, BotTestClient]], None]:
    default_timeout = tgmock_config.default_timeout
    created: list[BotTestClient] = []

    async def _make() -> BotTestClient:
        uid = next_user_id()
        client = BotTestClient(
            base_url=tg_runtime.base_url,
            user_id=uid,
            default_timeout=default_timeout,
        )
        created.append(client)
        await client.start()
        await client.clear()
        return client

    try:
        yield _make
    finally:
        for client in created:
            await client.clear()
            await client.stop()
