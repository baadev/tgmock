from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Sequence

Command = str | Sequence[str]


def normalize_command(command: Command | None) -> list[str]:
    """Normalize a command into argv without invoking a shell."""
    if command is None:
        return []
    if isinstance(command, str):
        argv = shlex.split(command)
    else:
        argv = [str(part) for part in command]
    if not argv:
        return []
    if any(not part for part in argv):
        raise ValueError("Command arguments must be non-empty strings")
    return argv


def command_preview(command: Command | None) -> str:
    argv = normalize_command(command)
    return shlex.join(argv) if argv else ""


def is_python_command(command: Command | None) -> bool:
    """Best-effort detection for Python entrypoints to enable auto-patch."""
    argv = normalize_command(command)
    if not argv:
        return False

    names = [Path(arg).name for arg in argv]
    first = names[0]
    if first.startswith("python"):
        return True

    if len(names) >= 3 and names[0] in {"uv", "poetry"} and names[1] == "run":
        return names[2].startswith("python")

    if first in {"bash", "sh", "zsh"} and len(argv) >= 3 and argv[1] in {"-c", "-lc"}:
        shell_words = shlex.split(argv[2])
        return bool(shell_words and Path(shell_words[0]).name.startswith("python"))

    return False


def prepend_pythonpath(existing_env: dict[str, str], path: str) -> str:
    current = existing_env.get("PYTHONPATH", "")
    return f"{path}{os.pathsep}{current}" if current else path
