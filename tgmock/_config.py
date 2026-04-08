from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from tgmock._commands import Command


@dataclass
class TgmockConfig:
    bot_command: Command | None = None
    port: int = 8999
    token: str = "test:token"
    settle_ms: int = 400
    ready_log: str | None = None
    startup_timeout: float = 15.0
    default_timeout: float = 25.0
    env_file: str = ".env"
    build_command: Command | None = None
    auto_patch: bool = True
    env: dict[str, str] = field(default_factory=dict)


def load_config(rootdir: Path) -> TgmockConfig:
    """
    Load tgmock config from TGMOCK_* env vars, falling back to pyproject.toml.

    Priority (highest to lowest):
      1. TGMOCK_* environment variables
      2. TGMOCK_* keys inside the project's .env file
      3. [tool.tgmock] section in pyproject.toml
      4. Built-in defaults
    """
    cfg = TgmockConfig()

    pyproject = rootdir / "pyproject.toml"
    if pyproject.exists():
        try:
            import tomllib

            with open(pyproject, "rb") as f:
                data = tomllib.load(f)
            raw: dict = data.get("tool", {}).get("tgmock", {})
            for key in (
                "bot_command",
                "build_command",
                "port",
                "settle_ms",
                "ready_log",
                "startup_timeout",
                "default_timeout",
                "env_file",
                "auto_patch",
                "token",
            ):
                if key in raw:
                    setattr(cfg, key, raw[key])
            cfg.env.update({str(k): str(v) for k, v in raw.get("env", {}).items()})
        except Exception:
            pass

    env_file = rootdir / cfg.env_file
    if env_file.exists():
        try:
            import dotenv

            file_vars = dotenv.dotenv_values(env_file)
            _apply_tgmock_vars(cfg, file_vars)
        except Exception:
            pass

    _apply_tgmock_vars(cfg, os.environ)
    return cfg


def _apply_tgmock_vars(cfg: TgmockConfig, mapping: dict) -> None:
    str_keys = {"ready_log", "env_file", "token"}
    int_keys = {"port", "settle_ms"}
    float_keys = {"startup_timeout", "default_timeout"}
    bool_keys = {"auto_patch"}
    command_keys = {"bot_command", "build_command"}

    for key in str_keys | int_keys | float_keys | bool_keys | command_keys:
        val = mapping.get(f"TGMOCK_{key.upper()}")
        if val is None:
            continue
        if key in int_keys:
            setattr(cfg, key, int(val))
        elif key in float_keys:
            setattr(cfg, key, float(val))
        elif key in bool_keys:
            normalized = val if isinstance(val, bool) else str(val).lower()
            setattr(cfg, key, normalized in (True, "1", "true", "yes", "on"))
        elif key in command_keys:
            setattr(cfg, key, str(val))
        else:
            setattr(cfg, key, str(val))
