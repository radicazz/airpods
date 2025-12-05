"""Plugin management utilities for Open WebUI."""

from __future__ import annotations

import shutil
from pathlib import Path

from airpods.logging import console
from airpods.paths import detect_repo_root


def get_plugins_source_dir() -> Path:
    """Get the source directory containing bundled plugins."""
    repo = detect_repo_root()
    if repo:
        return repo / "plugins" / "open-webui"
    return Path(__file__).parent.parent.parent / "plugins" / "open-webui"


def get_plugins_target_dir() -> Path:
    """Get the target directory where plugins should be copied."""
    from airpods.state import volumes_dir

    return volumes_dir() / "webui_plugins"


def sync_plugins(force: bool = False) -> int:
    """Sync bundled plugins to the webui_plugins volume directory.

    Args:
        force: If True, overwrite existing plugins even if they're newer.

    Returns:
        Number of plugins synced.
    """
    source_dir = get_plugins_source_dir()
    target_dir = get_plugins_target_dir()

    if not source_dir.exists():
        console.print(f"[warn]Plugin source directory not found: {source_dir}[/]")
        return 0

    target_dir.mkdir(parents=True, exist_ok=True)

    synced = 0
    plugin_files = list(source_dir.glob("*.py"))

    for plugin_file in plugin_files:
        if plugin_file.name == "__init__.py":
            continue

        target_file = target_dir / plugin_file.name

        should_copy = force or not target_file.exists()
        if not should_copy and target_file.exists():
            source_mtime = plugin_file.stat().st_mtime
            target_mtime = target_file.stat().st_mtime
            should_copy = source_mtime > target_mtime

        if should_copy:
            shutil.copy2(plugin_file, target_file)
            synced += 1

    return synced


def list_available_plugins() -> list[str]:
    """List all available bundled plugins."""
    source_dir = get_plugins_source_dir()
    if not source_dir.exists():
        return []

    return [
        p.stem
        for p in source_dir.glob("*.py")
        if p.name != "__init__.py" and not p.name.startswith("_")
    ]


def list_installed_plugins() -> list[str]:
    """List all installed plugins."""
    target_dir = get_plugins_target_dir()
    if not target_dir.exists():
        return []

    return [
        p.stem
        for p in target_dir.glob("*.py")
        if p.name != "__init__.py" and not p.name.startswith("_")
    ]
