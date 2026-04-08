from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from tgmock._commands import Command

_IGNORE_DIRS = {
    ".git",
    ".hg",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "site-packages",
    "tests",
    "vendor",
    "venv",
}

_PYTHON_NAME_SCORES = {
    "bot.py": 70,
    "main.py": 65,
    "app.py": 45,
    "run.py": 40,
    "__main__.py": 50,
}
_NODE_FILE_SCORES = {
    "bot.js": 65,
    "main.js": 60,
    "index.js": 50,
    "app.js": 45,
    "bot.mjs": 65,
    "main.mjs": 60,
    "index.mjs": 50,
    "app.mjs": 45,
    "bot.cjs": 65,
    "main.cjs": 60,
    "index.cjs": 50,
    "app.cjs": 45,
}
_GO_DIR_SCORES = {
    "bot": 70,
    "telegram": 65,
    "app": 55,
    "server": 50,
    "main": 45,
}
_PYTHON_MARKERS = ("aiogram", "telegram.ext", "telebot", "pyrogram", "BOT_API_BASE")
_NODE_MARKERS = ("telegraf", "node-telegram-bot-api", "grammy", "BOT_API_BASE")
_GO_MARKERS = ("go-telegram-bot-api", "tgbotapi", "gotgbot", "telebot", "BOT_API_BASE")
_NODE_TELEGRAM_DEPS = {"telegraf", "node-telegram-bot-api", "grammy", "puregram"}


@dataclass(slots=True)
class DiscoveryResult:
    runtime: str | None = None
    bot_command: Command | None = None
    build_command: Command | None = None
    reason: str | None = None


@dataclass(slots=True)
class _Candidate:
    runtime: str
    command: Command
    build_command: Command | None
    score: int
    reason: str


def discover_project(rootdir: Path) -> DiscoveryResult:
    candidates: list[_Candidate] = []
    if candidate := _discover_python(rootdir):
        candidates.append(candidate)
    if candidate := _discover_node(rootdir):
        candidates.append(candidate)
    if candidate := _discover_go(rootdir):
        candidates.append(candidate)

    if not candidates:
        return DiscoveryResult()

    best = max(candidates, key=lambda item: item.score)
    return DiscoveryResult(
        runtime=best.runtime,
        bot_command=best.command,
        build_command=best.build_command,
        reason=best.reason,
    )


def _discover_python(rootdir: Path) -> _Candidate | None:
    interpreter = _preferred_python(rootdir)
    candidates: list[_Candidate] = []
    for path in _walk_files(rootdir, suffixes={".py"}, max_depth=3):
        rel = path.relative_to(rootdir)
        name_score = _PYTHON_NAME_SCORES.get(path.name, 0)
        if name_score <= 0:
            continue
        text = _read_text(path)
        score = name_score
        if any(marker.lower() in text.lower() for marker in _PYTHON_MARKERS):
            score += 30
        if "__name__ == \"__main__\"" in text or "__name__ == '__main__'" in text:
            score += 10
        if "asyncio.run(" in text:
            score += 5
        if rel.parent == Path("."):
            score += 10
        elif rel.parent == Path("src"):
            score += 6

        if path.name == "__main__.py" and (path.parent / "__init__.py").exists():
            module = ".".join(path.parent.relative_to(rootdir).parts)
            command: Command = [interpreter, "-m", module]
            reason = f"python package entrypoint {module}"
        else:
            command = [interpreter, rel.as_posix()]
            reason = f"python file {rel.as_posix()}"
        candidates.append(
            _Candidate(runtime="python", command=command, build_command=None, score=score, reason=reason)
        )

    if not candidates:
        return None
    return max(candidates, key=lambda item: item.score)


def _discover_node(rootdir: Path) -> _Candidate | None:
    package_json = rootdir / "package.json"
    if not package_json.exists():
        return None
    try:
        payload = json.loads(package_json.read_text())
    except Exception:
        return None

    scripts = payload.get("scripts") or {}
    deps = {
        *map(str, (payload.get("dependencies") or {}).keys()),
        *map(str, (payload.get("devDependencies") or {}).keys()),
    }
    telegram_score = 30 if deps & _NODE_TELEGRAM_DEPS else 0
    candidates: list[_Candidate] = []

    for script_name, base_score in (("start", 85), ("dev", 75)):
        script = scripts.get(script_name)
        if not isinstance(script, str) or not script.strip():
            continue
        score = base_score + telegram_score
        reason = f"package.json script {script_name}"
        if script_target := _extract_script_target(rootdir, script):
            text = _read_text(script_target)
            if any(marker.lower() in text.lower() for marker in _NODE_MARKERS):
                score += 20
            reason = f"package.json script {script_name} -> {script_target.relative_to(rootdir).as_posix()}"
        candidates.append(
            _Candidate(
                runtime="node",
                command=_node_script_command(payload, script_name),
                build_command=None,
                score=score,
                reason=reason,
            )
        )

    main = payload.get("main")
    if isinstance(main, str) and main:
        main_path = rootdir / main
        if main_path.exists():
            score = 60 + telegram_score
            text = _read_text(main_path)
            if any(marker.lower() in text.lower() for marker in _NODE_MARKERS):
                score += 20
            candidates.append(
                _Candidate(
                    runtime="node",
                    command=["node", main_path.relative_to(rootdir).as_posix()],
                    build_command=None,
                    score=score,
                    reason=f"package.json main {main_path.relative_to(rootdir).as_posix()}",
                )
            )

    for path in _walk_files(rootdir, suffixes={".js", ".mjs", ".cjs"}, max_depth=3):
        rel = path.relative_to(rootdir)
        name_score = _NODE_FILE_SCORES.get(path.name, 0)
        if name_score <= 0:
            continue
        text = _read_text(path)
        score = name_score + telegram_score
        if any(marker.lower() in text.lower() for marker in _NODE_MARKERS):
            score += 20
        if rel.parent == Path("."):
            score += 10
        elif rel.parent == Path("src"):
            score += 5
        candidates.append(
            _Candidate(
                runtime="node",
                command=["node", rel.as_posix()],
                build_command=None,
                score=score,
                reason=f"node file {rel.as_posix()}",
            )
        )

    if not candidates:
        return None
    return max(candidates, key=lambda item: item.score)


def _discover_go(rootdir: Path) -> _Candidate | None:
    if not (rootdir / "go.mod").exists():
        return None

    candidates: list[_Candidate] = []
    root_main = rootdir / "main.go"
    if root_main.exists():
        score = 80
        text = _read_text(root_main)
        if any(marker.lower() in text.lower() for marker in _GO_MARKERS):
            score += 20
        candidates.append(
            _Candidate(
                runtime="go",
                command=["./.tgmock-go-bot"],
                build_command=_go_build_command(".tgmock-go-bot", "."),
                score=score,
                reason="go main package .",
            )
        )

    cmd_root = rootdir / "cmd"
    if cmd_root.exists():
        for path in sorted(cmd_root.glob("*/main.go")):
            name = path.parent.name.lower()
            score = 70 + _GO_DIR_SCORES.get(name, 0)
            text = _read_text(path)
            if any(marker.lower() in text.lower() for marker in _GO_MARKERS):
                score += 20
            candidates.append(
                _Candidate(
                    runtime="go",
                    command=[f"./.tgmock-go-{path.parent.name}"],
                    build_command=_go_build_command(f".tgmock-go-{path.parent.name}", f"./cmd/{path.parent.name}"),
                    score=score,
                    reason=f"go main package cmd/{path.parent.name}",
                )
            )

    if not candidates:
        return None
    return max(candidates, key=lambda item: item.score)


def _walk_files(rootdir: Path, *, suffixes: set[str], max_depth: int) -> list[Path]:
    matches: list[Path] = []
    for current, dirnames, filenames in os.walk(rootdir):
        current_path = Path(current)
        rel = current_path.relative_to(rootdir)
        depth = 0 if rel == Path(".") else len(rel.parts)
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if dirname not in _IGNORE_DIRS and depth < max_depth
        ]
        for filename in filenames:
            path = current_path / filename
            if path.suffix.lower() not in suffixes:
                continue
            matches.append(path)
    return matches


def _read_text(path: Path) -> str:
    try:
        return path.read_text(errors="ignore")
    except Exception:
        return ""


def _preferred_python(rootdir: Path) -> str:
    for candidate in (rootdir / ".venv" / "bin" / "python", rootdir / "venv" / "bin" / "python"):
        if candidate.exists():
            return str(candidate)
    for name in ("python3", "python"):
        if shutil.which(name):
            return name
    return sys.executable or "python"


def _node_script_command(package_json: dict, script_name: str) -> list[str]:
    package_manager = str(package_json.get("packageManager") or "")
    if package_manager.startswith("pnpm@") and shutil.which("pnpm"):
        return ["pnpm", script_name]
    if package_manager.startswith("yarn@") and shutil.which("yarn"):
        return ["yarn", script_name]
    return ["npm", "run", script_name]


def _extract_script_target(rootdir: Path, script: str) -> Path | None:
    try:
        argv = shlex.split(script)
    except ValueError:
        return None
    if len(argv) < 2 or Path(argv[0]).name not in {"node", "tsx", "ts-node"}:
        return None
    target = rootdir / argv[1]
    return target if target.exists() else None


def _go_build_command(output: str, package: str) -> list[str]:
    command = ["go", "build"]
    if sys.platform == "darwin":
        command.append("-ldflags=-linkmode external")
    command.extend(["-o", output, package])
    return command
