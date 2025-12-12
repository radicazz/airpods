"""Plugin management utilities for Open WebUI."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import NamedTuple

from airpods.logging import console
from airpods.paths import detect_repo_root
from airpods.state import volumes_dir

WEBUI_DB_PATH = "/app/backend/data/webui.db"
AIRPODS_OWNER_ID = "airpods-system"


class PluginModule(NamedTuple):
    """Container for plugin metadata used during imports/listing."""

    id: str
    path: Path
    content: str
    function_type: str


def _plugin_id_for_path(base_dir: Path, plugin_path: Path) -> str:
    """Generate a stable, unique function id for a plugin file.

    IDs are based on the relative path from the plugin root, with directory
    separators normalized to dots so nested plugins with the same basename
    do not collide (e.g., filters/foo.py -> filters.foo).
    """
    rel_no_suffix = plugin_path.relative_to(base_dir).with_suffix("")
    return rel_no_suffix.as_posix().replace("/", ".")


def _detect_function_type(content: str) -> str | None:
    """Best-effort guess of Open WebUI function type, or None for non-functions."""

    lowered = content.lower()
    if "def action(" in lowered:
        return "action"
    if "class pipeline" in lowered or "def pipe(" in lowered:
        return "pipeline"
    if "class filter" in lowered or "def inlet(" in lowered or "def outlet(" in lowered:
        return "filter"
    return None


def _discover_function_plugins(base_dir: Path) -> list[PluginModule]:
    """Return plugin modules that expose Filter/Pipeline/Action hooks."""

    if not base_dir.exists():
        return []

    modules: list[PluginModule] = []
    for plugin_file in base_dir.rglob("*.py"):
        if plugin_file.name == "__init__.py" or plugin_file.name.startswith("_"):
            continue
        try:
            content = plugin_file.read_text(encoding="utf-8")
        except OSError as exc:
            console.print(f"[warn]Unable to read plugin file {plugin_file}: {exc}[/]")
            continue

        function_type = _detect_function_type(content)
        if function_type is None:
            continue

        plugin_id = _plugin_id_for_path(base_dir, plugin_file)
        modules.append(PluginModule(plugin_id, plugin_file, content, function_type))

    return modules


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


def sync_plugins(force: bool = False, prune: bool = True) -> int:
    """Sync bundled plugins to the webui_plugins volume directory.

    Args:
        force: If True, overwrite existing plugins even if they're newer.
        prune: If True, delete plugin files in target that no longer exist in source.

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
        for p in source_dir.rglob("*.py")
        if p.name != "__init__.py" and not p.name.startswith("_")
    ]
    desired_relpaths = {p.relative_to(source_dir) for p in plugin_files}

    for plugin_file in plugin_files:
        target_file = target_dir / plugin_file.relative_to(source_dir)
        target_file.parent.mkdir(parents=True, exist_ok=True)

        should_copy = force or not target_file.exists()
        if not should_copy and target_file.exists():
            source_mtime = plugin_file.stat().st_mtime
            target_mtime = target_file.stat().st_mtime
            should_copy = source_mtime > target_mtime

        if should_copy:
            shutil.copy2(plugin_file, target_file)
            synced += 1

    if prune:
        for existing in target_dir.rglob("*.py"):
            rel = existing.relative_to(target_dir)
            if rel not in desired_relpaths and existing.name != "__init__.py":
                existing.unlink()

    return synced


def list_available_plugins() -> list[str]:
    """List all available bundled plugins."""
    source_dir = get_plugins_source_dir()
    modules = _discover_function_plugins(source_dir)
    return sorted({module.id for module in modules})


def list_installed_plugins() -> list[str]:
    """List all installed plugins."""
    target_dir = get_plugins_target_dir()
    modules = _discover_function_plugins(target_dir)
    return sorted({module.id for module in modules})


def _podman_exec_python(
    container_name: str, code: str, timeout: int = 10
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["podman", "exec", container_name, "python3", "-c", code],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _find_admin_user_id(container_name: str) -> str | None:
    """Best-effort lookup of an admin user id in Open WebUI."""
    code = """
import sqlite3
DB_PATH = r'/app/backend/data/webui.db'
queries = [
    "SELECT id FROM user WHERE role='admin' LIMIT 1",
    "SELECT id FROM user WHERE is_admin=1 LIMIT 1",
    "SELECT id FROM users WHERE role='admin' LIMIT 1",
    "SELECT id FROM users WHERE is_admin=1 LIMIT 1",
    "SELECT id FROM users WHERE type='admin' LIMIT 1",
]
try:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for q in queries:
        try:
            cur.execute(q)
            row = cur.fetchone()
            if row and row[0]:
                print(row[0])
                break
        except Exception:
            continue
finally:
    try:
        conn.close()
    except Exception:
        pass
"""
    try:
        result = _podman_exec_python(container_name, code.strip(), timeout=8)
    except Exception as exc:  # pragma: no cover - system specific
        console.print(f"[warn]Unable to query Open WebUI admin user: {exc}[/]")
        return None
    admin_id = (result.stdout or "").strip()
    return admin_id or None


def _ensure_airpods_owner(container_name: str) -> str | None:
    """Attempt to create a stable non-login owner user for plugin rows."""
    code = f"""
import json
import sqlite3
import time

DB_PATH = r'{WEBUI_DB_PATH}'
OWNER_ID = r'{AIRPODS_OWNER_ID}'

try:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    table = None
    for candidate in ("users", "user"):
        try:
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (candidate,),
            )
            if cur.fetchone():
                table = candidate
                break
        except Exception:
            continue

    if not table:
        raise RuntimeError("no user table found")

    cur.execute(f"SELECT id FROM {{table}} WHERE id=?", (OWNER_ID,))
    if cur.fetchone():
        print(OWNER_ID)
    else:
        cols = [r[1] for r in cur.execute(f"PRAGMA table_info({{table}})").fetchall()]
        now = int(time.time())
        data = {{"id": OWNER_ID}}
        if "name" in cols:
            data["name"] = "AirPods System"
        if "email" in cols:
            data["email"] = "airpods-system@local"
        if "username" in cols:
            data["username"] = "airpods"
        if "role" in cols:
            data["role"] = "admin"
        if "is_admin" in cols:
            data["is_admin"] = 1
        if "is_active" in cols:
            data["is_active"] = 1
        for key in ("created_at", "updated_at", "last_active_at"):
            if key in cols:
                data[key] = now
        if "settings" in cols:
            data["settings"] = json.dumps({{}})

        fields = [k for k, v in data.items() if v is not None]
        placeholders = ",".join("?" for _ in fields)
        sql = f"INSERT INTO {{table}} ({{','.join(fields)}}) VALUES ({{placeholders}})"
        cur.execute(sql, [data[k] for k in fields])
        conn.commit()
        print(OWNER_ID)
except Exception:
    pass
finally:
    try:
        conn.close()
    except Exception:
        pass
"""
    try:
        result = _podman_exec_python(container_name, code.strip(), timeout=8)
    except Exception as exc:  # pragma: no cover - system specific
        console.print(f"[warn]Unable to ensure airpods plugin owner: {exc}[/]")
        return None
    owner_id = (result.stdout or "").strip()
    return owner_id or None


def resolve_plugin_owner_user_id(container_name: str, mode: str = "auto") -> str:
    """Resolve which WebUI user id should own imported plugins.

    - auto: use an existing admin if possible, else ensure airpods-system owner.
    - admin: only use an existing admin, else fall back to 'system'.
    - airpods: ensure airpods-system owner, else fall back to 'system'.
    """
    normalized = (mode or "auto").lower()
    if normalized not in {"auto", "admin", "airpods"}:
        console.print(
            f"[warn]Unknown cli.plugin_owner '{mode}'; falling back to auto[/]"
        )
        normalized = "auto"

    if normalized in {"auto", "admin"}:
        admin_id = _find_admin_user_id(container_name)
        if admin_id:
            return admin_id
        if normalized == "admin":
            console.print(
                "[warn]No admin user found for Open WebUI; plugins will be owned by 'system'.[/]"
            )
            return "system"

    if normalized in {"auto", "airpods"}:
        owner_id = _ensure_airpods_owner(container_name)
        if owner_id:
            return owner_id
        if normalized == "airpods":
            console.print(
                "[warn]Unable to create airpods plugin owner; falling back to 'system'.[/]"
            )

    return "system"


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
    modules = _discover_function_plugins(plugins_dir)
    timestamp = int(time.time())

    for module in modules:
        try:
            function_id = module.id
            function_name = module.path.stem.replace("_", " ").title()
            content = module.content
            function_type = module.function_type
            rel_display = module.path.relative_to(plugins_dir).as_posix()

            # Escape single quotes for SQL
            content_escaped = content.replace("'", "''")

            # Create meta JSON
            meta = {
                "description": f"Auto-imported from {rel_display} (type: {function_type})",
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
                '{function_name}',
                '{function_type}',
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
            console.print(f"[error]Error importing {module.path.name}: {e}[/]")

    return imported
