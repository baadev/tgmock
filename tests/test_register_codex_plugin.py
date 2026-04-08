from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_register_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "register_codex_plugin.py"
    spec = importlib.util.spec_from_file_location("register_codex_plugin", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_sync_cache_copy_refreshes_cached_bundle(tmp_path):
    module = _load_register_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("fresh bundle\n")
    (repo_root / ".venv").mkdir()
    (repo_root / ".venv" / "ignore.txt").write_text("ignore me\n")

    cache_dir = tmp_path / "cache"
    cached_bundle = module.plugin_cache_path(cache_dir, "tgmock")
    cached_bundle.mkdir(parents=True)
    (cached_bundle / "README.md").write_text("stale bundle\n")

    destination, status = module.sync_cache_copy(repo_root, "tgmock", cache_dir)

    assert destination == cached_bundle
    assert status == "refreshed"
    assert (cached_bundle / "README.md").read_text() == "fresh bundle\n"
    assert not (cached_bundle / ".venv").exists()
