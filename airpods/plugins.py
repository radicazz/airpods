"""Plugin management utilities for Open WebUI."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from airpods.logging import console
from airpods.paths import detect_repo_root
from airpods import state

WEBUI_DB_PATH = "/app/backend/data/webui.db"


def detect_plugin_type(content: str) -> str:
    """Detect plugin type from its class definition.
    
    Returns:
        'tool' for Tools class
        'filter' for Filter class
        'pipeline' for Pipeline class
        'function' for Function class (generic)
        'unknown' if no recognized class found
    """
    if re.search(r"^class Tools:", content, re.MULTILINE):
        return "tool"
    elif re.search(r"^class Filter:", content, re.MULTILINE):
        return "filter"
    elif re.search(r"^class Pipeline:", content, re.MULTILINE):
        return "pipeline"
    elif re.search(r"^class Function:", content, re.MULTILINE):
        return "function"
    else:
        return "unknown"


def get_plugins_source_dir() -> Path:
    """Get the source directory containing bundled plugins."""
    source_root = detect_repo_root(Path(__file__).resolve())
    if source_root is None:
        # When installed as a package, fall back to the site-packages root
        source_root = Path(__file__).resolve().parent.parent
    return source_root / "plugins" / "open-webui"


def get_plugins_target_dir() -> Path:
    """Get the target directory where plugins should be copied."""
    return state.volumes_dir() / "webui_plugins"


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
    # Recursively find all .py files in subdirectories
    plugin_files = [
        p
        for p in source_dir.rglob("*.py")
        if p.name != "__init__.py" and not p.name.startswith("_")
    ]

    for plugin_file in plugin_files:
        # Preserve directory structure relative to source_dir
        relative_path = plugin_file.relative_to(source_dir)
        target_file = target_dir / relative_path
        
        # Create subdirectories if needed
        target_file.parent.mkdir(parents=True, exist_ok=True)

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
        str(p.relative_to(source_dir))
        for p in source_dir.rglob("*.py")
        if p.name != "__init__.py" and not p.name.startswith("_")
    ]


def list_installed_plugins() -> list[str]:
    """List all installed plugins."""
    target_dir = get_plugins_target_dir()
    if not target_dir.exists():
        return []

    return [
        str(p.relative_to(target_dir))
        for p in target_dir.rglob("*.py")
        if p.name != "__init__.py" and not p.name.startswith("_")
    ]


def ensure_airpods_admin_user(container_name: str = "open-webui-0") -> str:
    """Ensure airpods admin user exists in Open WebUI database.
    
    Creates a default admin account 'airpods' with:
    - Username: Airpods Admin
    - Email: airpods@localhost
    - Role: admin
    - Password: random secure token stored in $AIRPODS_HOME/configs/webui_admin_password
    
    Args:
        container_name: Name of the Open WebUI container
    
    Returns:
        The user ID of the airpods admin account
    
    Raises:
        Exception: If user creation or verification fails
    """
    email = "airpods@localhost"
    timestamp = int(time.time())
    
    # Check if user already exists
    check_sql = f"SELECT id FROM user WHERE email = '{email}' LIMIT 1;"
    
    cmd = [
        "podman",
        "exec",
        container_name,
        "python3",
        "-c",
        f"import sqlite3; "
        f"conn = sqlite3.connect('{WEBUI_DB_PATH}'); "
        f"cursor = conn.cursor(); "
        f"cursor.execute({repr(check_sql)}); "
        f"result = cursor.fetchone(); "
        f"print(result[0] if result else ''); "
        f"conn.close()",
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    
    if result.returncode == 0 and result.stdout.strip():
        # User already exists, return the ID
        user_id = result.stdout.strip()
        return user_id
    
    # User doesn't exist, create it
    user_id = str(uuid.uuid4())
    password = state.ensure_webui_admin_password()
    
    # Hash password using bcrypt inside the container
    hash_cmd = [
        "podman",
        "exec",
        container_name,
        "python3",
        "-c",
        f"import bcrypt; "
        f"print(bcrypt.hashpw({repr(password.encode())}, bcrypt.gensalt()).decode())",
    ]
    
    hash_result = subprocess.run(hash_cmd, capture_output=True, text=True, timeout=10)
    
    if hash_result.returncode != 0:
        raise Exception(f"Failed to hash password: {hash_result.stderr}")
    
    password_hash = hash_result.stdout.strip()
    password_hash_escaped = password_hash.replace("'", "''")
    
    # Create user in user table
    create_user_sql = f"""
    INSERT INTO user (
        id, name, email, role, profile_image_url,
        created_at, updated_at, last_active_at
    ) VALUES (
        '{user_id}',
        'Airpods Admin',
        '{email}',
        'admin',
        '/static/favicon.png',
        {timestamp},
        {timestamp},
        {timestamp}
    );
    """
    
    # Create auth entry in auth table
    create_auth_sql = f"""
    INSERT INTO auth (
        id, email, password, active
    ) VALUES (
        '{user_id}',
        '{email}',
        '{password_hash_escaped}',
        1
    );
    """
    
    # Execute both inserts in a transaction
    create_cmd = [
        "podman",
        "exec",
        container_name,
        "python3",
        "-c",
        f"import sqlite3; "
        f"conn = sqlite3.connect('{WEBUI_DB_PATH}'); "
        f"cursor = conn.cursor(); "
        f"cursor.execute({repr(create_user_sql)}); "
        f"cursor.execute({repr(create_auth_sql)}); "
        f"conn.commit(); "
        f"print('Created user:', cursor.lastrowid); "
        f"conn.close()",
    ]
    
    create_result = subprocess.run(
        create_cmd, capture_output=True, text=True, timeout=10
    )
    
    if create_result.returncode != 0:
        raise Exception(f"Failed to create user: {create_result.stderr}")
    
    return user_id


def import_plugins_to_webui(
    plugins_dir: Path,
    admin_user_id: str = "system",
    container_name: str = "open-webui-0",
) -> int:
    """Import plugins directly into Open WebUI database via SQL.

    This bypasses the API entirely and inserts functions/tools directly into
    the SQLite database using podman exec.

    Args:
        plugins_dir: Directory containing plugin .py files (including subdirectories)
        admin_user_id: User ID to assign as owner (default: "system")
        container_name: Name of the Open WebUI container

    Returns:
        Number of plugins successfully imported
    """
    if not plugins_dir.exists():
        console.print(f"[warn]Plugins directory not found: {plugins_dir}[/]")
        return 0

    imported = 0
    # Recursively find all .py files
    plugin_files = [p for p in plugins_dir.rglob("*.py") if p.name != "__init__.py"]
    timestamp = int(time.time())

    for plugin_file in plugin_files:
        try:
            function_id = plugin_file.stem
            content = plugin_file.read_text(encoding="utf-8")
            
            # Detect plugin type from class definition
            plugin_type = detect_plugin_type(content)
            
            if plugin_type == "unknown":
                console.print(
                    f"[warn]Skipping {plugin_file.name}: No recognized class found[/]"
                )
                continue

            # Escape single quotes for SQL
            content_escaped = content.replace("'", "''")

            # Create meta JSON
            meta = {
                "description": f"Auto-imported from {plugin_file.name}",
                "manifest": {},
            }
            meta_json = json.dumps(meta).replace("'", "''")
            
            display_name = function_id.replace("_", " ").title()

            # Build appropriate SQL based on plugin type
            if plugin_type == "tool":
                # Tools go into the 'tool' table
                sql = f"""
                INSERT INTO tool (
                    id, user_id, name, content, specs, meta,
                    created_at, updated_at
                ) VALUES (
                    '{function_id}',
                    '{admin_user_id}',
                    '{display_name}',
                    '{content_escaped}',
                    '[]',
                    '{meta_json}',
                    {timestamp},
                    {timestamp}
                )
                ON CONFLICT(id) DO UPDATE SET
                    content = excluded.content,
                    updated_at = excluded.updated_at;
                """
            else:
                # Filters, Pipelines, Functions go into the 'function' table
                sql = f"""
                INSERT INTO function (
                    id, user_id, name, type, content, meta,
                    created_at, updated_at, is_active, is_global
                ) VALUES (
                    '{function_id}',
                    '{admin_user_id}',
                    '{display_name}',
                    '{plugin_type}',
                    '{content_escaped}',
                    '{meta_json}',
                    {timestamp},
                    {timestamp},
                    1,
                    0
                )
                ON CONFLICT(id) DO UPDATE SET
                    content = excluded.content,
                    type = excluded.type,
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
                f"print('Imported {function_id} ({plugin_type}):', cursor.rowcount); "
                f"conn.close()",
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

            if result.returncode == 0 and "Imported" in result.stdout:
                imported += 1
                table = "tool" if plugin_type == "tool" else "function"
                console.print(
                    f"[dim]  → {function_id} ({plugin_type} → {table} table)[/]"
                )
            else:
                console.print(
                    f"[warn]Failed to import {function_id}: {result.stderr}[/]"
                )

        except Exception as e:
            console.print(f"[error]Error importing {plugin_file.name}: {e}[/]")

    return imported
