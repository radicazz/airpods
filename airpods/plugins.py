"""Plugin management utilities for Open WebUI."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

from airpods.logging import console
from airpods.paths import detect_repo_root
from airpods.state import volumes_dir

WEBUI_DB_PATH = "/app/backend/data/webui.db"


def get_plugins_source_dir() -> Path:
    """Get the source directory containing bundled plugins."""
    source_root = detect_repo_root(Path(__file__).resolve())
    if source_root is None:
        # When installed as a package, fall back to the site-packages root
        source_root = Path(__file__).resolve().parent.parent
    return source_root / "plugins" / "open-webui"


def get_plugins_target_dir() -> Path:
    """Get the target directory where plugins should be copied."""
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
    plugin_files = [
        p
        for p in source_dir.glob("*.py")
        if p.name != "__init__.py" and not p.name.startswith("_")
    ]
    desired_names = {p.name for p in plugin_files}

    for plugin_file in plugin_files:
        target_file = target_dir / plugin_file.name

        should_copy = force or not target_file.exists()
        if not should_copy and target_file.exists():
            source_mtime = plugin_file.stat().st_mtime
            target_mtime = target_file.stat().st_mtime
            should_copy = source_mtime > target_mtime

        if should_copy:
            shutil.copy2(plugin_file, target_file)
            synced += 1

    # Pruning removed to preserve user-added plugins
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


def import_plugins_to_webui(
    plugins_dir: Path,
    admin_user_id: str = "system",
    container_name: str = "open-webui-0",
) -> int:
    """Import plugins directly into Open WebUI database via SQL.

    This bypasses the API entirely and inserts functions directly into
    the SQLite database using podman exec.

    Args:
        plugins_dir: Directory containing plugin .py files
        admin_user_id: User ID to assign as owner (default: "system")
        container_name: Name of the Open WebUI container

    Returns:
        Number of plugins successfully imported
    """
    if not plugins_dir.exists():
        console.print(f"[warn]Plugins directory not found: {plugins_dir}[/]")
        return 0

    imported = 0
    plugin_files = [p for p in plugins_dir.glob("*.py") if p.name != "__init__.py"]
    timestamp = int(time.time())

    for plugin_file in plugin_files:
        try:
            function_id = plugin_file.stem
            content = plugin_file.read_text(encoding="utf-8")

            # Escape single quotes for SQL
            content_escaped = content.replace("'", "''")

            # Create meta JSON
            meta = {
                "description": f"Auto-imported from {plugin_file.name}",
                "manifest": {},
            }
            meta_json = json.dumps(meta).replace("'", "''")

            # Build SQL INSERT with ON CONFLICT (upsert)
            sql = f"""
            INSERT INTO function (
                id, user_id, name, type, content, meta,
                created_at, updated_at, is_active, is_global
            ) VALUES (
                '{function_id}',
                '{admin_user_id}',
                '{function_id.replace("_", " ").title()}',
                'filter',
                '{content_escaped}',
                '{meta_json}',
                {timestamp},
                {timestamp},
                1,
                0
            )
            ON CONFLICT(id) DO UPDATE SET
                content = excluded.content,
                updated_at = excluded.updated_at;
            """

            # Execute via podman exec
            cmd = [
                "podman",
                "exec",
                container_name,
                "python3",
                "-c",
                f"import sqlite3; "
                f"conn = sqlite3.connect('{WEBUI_DB_PATH}'); "
                f"cursor = conn.cursor(); "
                f"cursor.execute({repr(sql)}); "
                f"conn.commit(); "
                f"print('Imported {function_id}:', cursor.rowcount); "
                f"conn.close()",
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

            if result.returncode == 0 and "Imported" in result.stdout:
                imported += 1
            else:
                console.print(
                    f"[warn]Failed to import {function_id}: {result.stderr}[/]"
                )

        except Exception as e:
            console.print(f"[error]Error importing {plugin_file.name}: {e}[/]")

    return imported
