#!/usr/bin/env python3
"""Register this checkout as a user-local Codex plugin."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_MARKETPLACE_NAME = "local-plugins"
DEFAULT_MARKETPLACE_DISPLAY_NAME = "Local Plugins"
DEFAULT_INSTALL_POLICY = "AVAILABLE"
DEFAULT_AUTH_POLICY = "ON_INSTALL"
DEFAULT_CATEGORY = "Developer Tools"


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parent.parent
    home = Path.home()

    parser = argparse.ArgumentParser(
        description="Register this checkout as a user-local Codex plugin."
    )
    parser.add_argument(
        "--repo-root",
        default=str(repo_root),
        help="Path to the tgmock repository checkout.",
    )
    parser.add_argument(
        "--plugins-dir",
        default=str(home / "plugins"),
        help="Directory that holds user-local Codex plugins.",
    )
    parser.add_argument(
        "--marketplace-path",
        default=str(home / ".agents" / "plugins" / "marketplace.json"),
        help="Path to the user-local Codex marketplace file.",
    )
    return parser.parse_args()


def load_manifest(repo_root: Path) -> dict[str, Any]:
    manifest_path = repo_root / ".codex-plugin" / "plugin.json"
    with manifest_path.open() as handle:
        payload = json.load(handle)

    if not isinstance(payload, dict):
        raise ValueError(f"{manifest_path} must contain a JSON object.")
    return payload


def build_entry(plugin_name: str, category: str) -> dict[str, Any]:
    return {
        "name": plugin_name,
        "source": {
            "source": "local",
            "path": f"./plugins/{plugin_name}",
        },
        "policy": {
            "installation": DEFAULT_INSTALL_POLICY,
            "authentication": DEFAULT_AUTH_POLICY,
        },
        "category": category,
    }


def ensure_symlink(link_path: Path, target_path: Path) -> str:
    link_path.parent.mkdir(parents=True, exist_ok=True)

    if link_path.is_symlink():
        if link_path.resolve() == target_path:
            return "unchanged"
        link_path.unlink()
    elif link_path.exists():
        raise FileExistsError(
            f"{link_path} already exists and is not a symlink. Remove it or choose another path."
        )

    link_path.symlink_to(target_path, target_is_directory=True)
    return "created"


def load_marketplace(path: Path) -> dict[str, Any]:
    if path.exists():
        with path.open() as handle:
            payload = json.load(handle)
    else:
        payload = {
            "name": DEFAULT_MARKETPLACE_NAME,
            "interface": {
                "displayName": DEFAULT_MARKETPLACE_DISPLAY_NAME,
            },
            "plugins": [],
        }

    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object.")

    payload.setdefault("name", DEFAULT_MARKETPLACE_NAME)
    interface = payload.setdefault("interface", {})
    if not isinstance(interface, dict):
        raise ValueError(f"{path} field 'interface' must be an object.")
    interface.setdefault("displayName", DEFAULT_MARKETPLACE_DISPLAY_NAME)

    plugins = payload.setdefault("plugins", [])
    if not isinstance(plugins, list):
        raise ValueError(f"{path} field 'plugins' must be an array.")

    return payload


def upsert_plugin_entry(plugins: list[dict[str, Any]], entry: dict[str, Any]) -> str:
    for index, existing in enumerate(plugins):
        if not isinstance(existing, dict):
            continue
        if existing.get("name") != entry["name"]:
            continue
        if existing == entry:
            return "unchanged"
        plugins[index] = entry
        return "updated"

    plugins.append(entry)
    return "created"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def main() -> None:
    args = parse_args()
    repo_root = Path(args.repo_root).expanduser().resolve()
    plugins_dir = Path(args.plugins_dir).expanduser().resolve()
    marketplace_path = Path(args.marketplace_path).expanduser().resolve()

    if not repo_root.exists():
        raise FileNotFoundError(f"Repository path does not exist: {repo_root}")

    manifest = load_manifest(repo_root)
    plugin_name = manifest.get("name")
    if not isinstance(plugin_name, str) or not plugin_name:
        raise ValueError("Plugin manifest must define a non-empty 'name'.")

    interface = manifest.get("interface")
    category = DEFAULT_CATEGORY
    if isinstance(interface, dict):
        raw_category = interface.get("category")
        if isinstance(raw_category, str) and raw_category:
            category = raw_category

    symlink_path = plugins_dir / plugin_name
    symlink_status = ensure_symlink(symlink_path, repo_root)

    marketplace = load_marketplace(marketplace_path)
    entry_status = upsert_plugin_entry(
        marketplace["plugins"],
        build_entry(plugin_name, category),
    )
    write_json(marketplace_path, marketplace)

    print(f"Plugin: {plugin_name}")
    print(f"Symlink: {symlink_path} -> {repo_root} ({symlink_status})")
    print(f"Marketplace: {marketplace_path} ({entry_status})")


if __name__ == "__main__":
    main()
