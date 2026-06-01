"""Plugin management utilities for Open WebUI."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import NamedTuple

import requests

from airpods.logging import console
from airpods.paths import detect_repo_root
from airpods.state import volumes_dir

WEBUI_DB_PATH = "/app/backend/data/webui.db"
AIRPODS_OWNER_ID = "airpods-system"
SQLITE_LOCK_MARKERS = (
    "database is locked",
    "database table is locked",
    "sqlite_busy",
)
SQLITE_IMPORT_MAX_ATTEMPTS = 6
SQLITE_IMPORT_INITIAL_RETRY_DELAY = 0.25
SQLITE_IMPORT_MAX_RETRY_DELAY = 2.0
SQLITE_IMPORT_BUSY_TIMEOUT_MS = 30_000
SQLITE_IMPORT_EXEC_TIMEOUT_SECONDS = 35

DEFAULT_ADMIN_EMAIL = "admin@airpods"
DEFAULT_ADMIN_PASSWORD = "admin"
WEBUI_API_CONNECT_TIMEOUT = 5.0
WEBUI_API_READ_TIMEOUT = 10.0


class PluginModule(NamedTuple):
    """Container for plugin metadata used during imports/listing."""

    id: str
    path: Path
    content: str
    function_type: str


def _is_sqlite_lock_error(output: str) -> bool:
    """Return True when output suggests a transient SQLite lock error."""

    lowered = (output or "").lower()
    return any(marker in lowered for marker in SQLITE_LOCK_MARKERS)


def _is_sqlite_retryable_error(
    output: str = "",
    *,
    error: BaseException | None = None,
) -> bool:
    """Return True for transient lock-contention errors worth retrying."""

    if isinstance(error, subprocess.TimeoutExpired):
        return True
    return _is_sqlite_lock_error(output)


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
    """Get the source directory containing bundled Open WebUI plugins."""
    source_root = detect_repo_root(Path(__file__).resolve())
    if source_root is None:
        # When installed as a package, fall back to the site-packages root
        source_root = Path(__file__).resolve().parent.parent
    return source_root / "plugins" / "open-webui"


def get_plugins_target_dir() -> Path:
    """Get the target directory where Open WebUI plugins should be copied."""
    return volumes_dir() / "webui_plugins"


def get_comfyui_plugins_source_dir() -> Path:
    """Get the source directory containing bundled ComfyUI custom nodes."""
    source_root = detect_repo_root(Path(__file__).resolve())
    if source_root is None:
        # When installed as a package, fall back to the site-packages root
        source_root = Path(__file__).resolve().parent.parent
    return source_root / "plugins" / "comfyui" / "custom_nodes"


def get_comfyui_plugins_target_dir() -> Path:
    """Get the target directory where ComfyUI custom nodes should be copied."""
    return volumes_dir() / "comfyui_custom_nodes"


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


def sync_comfyui_plugins(
    force: bool = False, prune: bool = True, keep: set[str] | None = None
) -> int:
    """Sync bundled ComfyUI custom nodes to the comfyui_custom_nodes volume directory.

    ComfyUI custom nodes can be either:
    - Directory-based packages (with __init__.py)
    - Single .py files

    Args:
        force: If True, overwrite existing custom nodes even if they're newer.
        prune: If True, delete custom nodes in target that no longer exist in source.
        keep: Optional set of relative paths to preserve during pruning.

    Returns:
        Number of custom nodes synced (directories + files).
    """
    source_dir = get_comfyui_plugins_source_dir()
    target_dir = get_comfyui_plugins_target_dir()

    if not source_dir.exists():
        console.print(
            f"[warn]ComfyUI plugins source directory not found: {source_dir}[/]"
        )
        return 0

    target_dir.mkdir(parents=True, exist_ok=True)

    synced = 0

    # Track what we're syncing (for pruning)
    desired_dirs: set[Path] = set()
    desired_files: set[Path] = set()

    # Sync directory-based custom nodes (Python packages)
    for item in source_dir.iterdir():
        if not item.is_dir() or item.name.startswith((".", "_")):
            continue

        # Skip if not a Python package (no __init__.py)
        if not (item / "__init__.py").exists():
            continue

        rel_path = item.relative_to(source_dir)
        desired_dirs.add(rel_path)
        target_item = target_dir / rel_path

        should_copy = force or not target_item.exists()
        if not should_copy and target_item.exists():
            # Compare modification times of the entire directory tree
            source_mtime = max(
                (f.stat().st_mtime for f in item.rglob("*") if f.is_file()),
                default=0,
            )
            target_mtime = max(
                (f.stat().st_mtime for f in target_item.rglob("*") if f.is_file()),
                default=0,
            )
            should_copy = source_mtime > target_mtime

        if should_copy:
            if target_item.exists():
                shutil.rmtree(target_item)
            shutil.copytree(item, target_item)
            synced += 1

    # Sync single-file custom nodes (.py files)
    for item in source_dir.iterdir():
        if not item.is_file() or not item.name.endswith(".py"):
            continue
        if item.name.startswith("_"):
            continue

        rel_path = item.relative_to(source_dir)
        desired_files.add(rel_path)
        target_item = target_dir / rel_path

        should_copy = force or not target_item.exists()
        if not should_copy and target_item.exists():
            source_mtime = item.stat().st_mtime
            target_mtime = target_item.stat().st_mtime
            should_copy = source_mtime > target_mtime

        if should_copy:
            shutil.copy2(item, target_item)
            synced += 1

    # Prune removed custom nodes
    keep_set = {entry for entry in (keep or set()) if entry}
    if prune:
        for item in target_dir.iterdir():
            rel_path = item.relative_to(target_dir)
            if rel_path.as_posix() in keep_set:
                continue
            if item.is_dir():
                if rel_path not in desired_dirs and not item.name.startswith(
                    (".", "_")
                ):
                    shutil.rmtree(item)
            elif item.is_file() and item.name.endswith(".py"):
                if rel_path.as_posix() in keep_set:
                    continue
                if rel_path not in desired_files and not item.name.startswith("_"):
                    item.unlink()

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


def count_comfyui_plugins() -> int:
    """Count the number of installed ComfyUI custom nodes.

    Returns:
        Total count of custom node directories and single-file nodes.
    """
    target_dir = get_comfyui_plugins_target_dir()
    if not target_dir.exists():
        return 0

    count = 0

    # Count directory-based custom nodes (Python packages)
    for item in target_dir.iterdir():
        if item.is_dir() and not item.name.startswith((".", "_")):
            if (item / "__init__.py").exists():
                count += 1

    # Count single-file custom nodes
    for item in target_dir.iterdir():
        if (
            item.is_file()
            and item.name.endswith(".py")
            and not item.name.startswith("_")
        ):
            count += 1

    return count


def _runtime_exec_python(
    runtime, container_name: str, code: str, timeout: int = 10
) -> subprocess.CompletedProcess[str]:
    """Execute Python code inside a container using the runtime abstraction."""
    return runtime.exec_in_container(
        container_name,
        ["python3", "-c", code],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _find_admin_user_id(runtime, container_name: str) -> str | None:
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
        result = _runtime_exec_python(runtime, container_name, code.strip(), timeout=8)
    except Exception as exc:  # pragma: no cover - system specific
        console.print(f"[warn]Unable to query Open WebUI admin user: {exc}[/]")
        return None
    admin_id = (result.stdout or "").strip()
    return admin_id or None


def _any_users_exist(runtime, container_name: str) -> bool:
    """Check if any users exist in the Open WebUI database."""
    code = """
import sqlite3
DB_PATH = r'/app/backend/data/webui.db'
try:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for table in ("user", "users"):
        try:
            # table is from a hardcoded tuple — safe to interpolate
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            count = cur.fetchone()[0]
            if count > 0:
                print("1")
                break
        except Exception:
            continue
    conn.close()
except Exception:
    pass
"""
    try:
        result = _runtime_exec_python(runtime, container_name, code.strip(), timeout=8)
    except Exception:  # pragma: no cover - system specific
        return False
    return (result.stdout or "").strip() == "1"


def _ensure_default_admin(runtime, container_name: str) -> str | None:
    """Create a default admin account with known credentials for first-time setup."""
    code = f"""
import json
import sqlite3
import time

DB_PATH = r'{WEBUI_DB_PATH}'
ADMIN_EMAIL = '{DEFAULT_ADMIN_EMAIL}'

try:
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    hashed = pwd_context.hash("{DEFAULT_ADMIN_PASSWORD}")
except Exception:
    # Fallback to bcrypt directly if passlib not available
    import bcrypt
    hashed = bcrypt.hashpw("{DEFAULT_ADMIN_PASSWORD}".encode(), bcrypt.gensalt()).decode()

try:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    table = None
    for candidate in ("user", "users"):
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

    # Whitelist guard: table name comes from schema inspection above,
    # but we double-check against the known set before using it in SQL.
    if table not in ("user", "users"):
        raise RuntimeError(f"unexpected user table name: {{table!r}}")

    # Check if admin already exists
    cur.execute(f"SELECT id FROM {{table}} WHERE email=?", (ADMIN_EMAIL,))
    existing = cur.fetchone()
    if existing:
        print(existing[0])
    else:
        # Create new admin user
        cols = [r[1] for r in cur.execute(f"PRAGMA table_info({{table}})").fetchall()]
        now = int(time.time())

        import uuid
        admin_id = str(uuid.uuid4())

        data = {{"id": admin_id, "email": ADMIN_EMAIL, "password": hashed}}
        if "name" in cols:
            data["name"] = "Admin"
        if "username" in cols:
            data["username"] = "admin"
        if "role" in cols:
            data["role"] = "admin"
        if "profile_image_url" in cols:
            data["profile_image_url"] = ""
        if "is_admin" in cols:
            data["is_admin"] = 1
        if "is_active" in cols:
            data["is_active"] = 1
        if "active" in cols:
            data["active"] = 1
        if "timestamp" in cols:
            data["timestamp"] = now
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
        print(admin_id)
except Exception as e:
    import traceback
    print(f"ERROR: {{e}}", file=__import__('sys').stderr)
    traceback.print_exc()
finally:
    try:
        conn.close()
    except Exception:
        pass
"""
    try:
        result = _runtime_exec_python(runtime, container_name, code.strip(), timeout=10)
    except Exception as exc:  # pragma: no cover - system specific
        console.print(f"[warn]Unable to create default admin: {exc}[/]")
        return None

    if result.returncode != 0 and result.stderr:
        console.print(f"[warn]Error creating admin: {result.stderr}[/]")
        return None

    admin_id = (result.stdout or "").strip()
    return admin_id or None


def _ensure_airpods_owner(container_name: str) -> str | None:
    """Create airpods-system user for 'airpods' mode (no password, cannot login)."""
    # For backwards compatibility - creates a non-login system user
    # This is only used when mode='airpods' explicitly
    return None  # Deprecated in favor of default admin


def resolve_plugin_owner_user_id(
    runtime, container_name: str, mode: str = "auto"
) -> str:
    """Resolve which WebUI user id should own imported plugins.

    - auto: use an existing admin if possible; if no users exist, use 'system' to allow
            normal first-user signup; only create airpods-system if users exist but no admin.
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
        admin_id = _find_admin_user_id(runtime, container_name)
        if admin_id:
            return admin_id
        if normalized == "admin":
            console.print(
                "[warn]No admin user found for Open WebUI; plugins will be owned by 'system'.[/]"
            )
            return "system"

    # In auto mode, create a default admin if no users exist
    if normalized == "auto":
        if not _any_users_exist(runtime, container_name):
            admin_id = _ensure_default_admin(runtime, container_name)
            if admin_id:
                console.print(
                    f"[info]Created default admin account: {DEFAULT_ADMIN_EMAIL} / {DEFAULT_ADMIN_PASSWORD} "
                    "(change password in Settings)[/]"
                )
                return admin_id
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


def _webui_signin(base_url: str, email: str, password: str) -> str | None:
    """Obtain a JWT bearer token from Open WebUI via the signin endpoint.

    Returns the token string on success, or None on any failure (connection
    error, wrong credentials, unexpected response shape, etc.). The caller
    is responsible for graceful degradation when None is returned.
    """
    url = f"{base_url.rstrip('/')}/api/v1/auths/signin"
    try:
        response = requests.post(
            url,
            json={"email": email, "password": password},
            timeout=(WEBUI_API_CONNECT_TIMEOUT, WEBUI_API_READ_TIMEOUT),
        )
        response.raise_for_status()
        token = response.json().get("token")
        return token if isinstance(token, str) and token else None
    except Exception:
        return None


def reload_functions_via_api(
    base_url: str,
    token: str,
    modules: list[PluginModule],
) -> int:
    """Push each module into Open WebUI's live function cache via the update endpoint.

    Calling POST /api/v1/functions/id/{id}/update causes OWU to re-exec the
    function source and refresh its in-memory state — without this, functions
    written directly to SQLite only become active after an OWU restart.

    Returns the number of functions successfully reloaded. Per-module failures
    are silently swallowed; the DB write already succeeded.
    """
    reloaded = 0
    headers = {"Authorization": f"Bearer {token}"}
    for module in modules:
        url = f"{base_url.rstrip('/')}/api/v1/functions/id/{module.id}/update"
        try:
            response = requests.post(
                url,
                json={"id": module.id, "content": module.content},
                headers=headers,
                timeout=(WEBUI_API_CONNECT_TIMEOUT, WEBUI_API_READ_TIMEOUT),
            )
            response.raise_for_status()
            reloaded += 1
        except Exception:
            pass
    return reloaded


def import_plugins_to_webui(
    runtime,
    plugins_dir: Path,
    admin_user_id: str = "system",
    container_name: str = "open-webui-0",
) -> list[PluginModule]:
    """Import plugins directly into Open WebUI database via SQL.

    This bypasses the API entirely and inserts functions directly into
    the SQLite database using runtime exec.

    Args:
        runtime: Container runtime instance
        plugins_dir: Directory containing plugin .py files
        admin_user_id: User ID to assign as owner (default: "system")
        container_name: Name of the Open WebUI container

    Returns:
        List of PluginModule objects that were successfully imported into the database.
    """
    if not plugins_dir.exists():
        console.print(f"[warn]Plugins directory not found: {plugins_dir}[/]")
        return []

    imported: list[PluginModule] = []
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
                user_id = excluded.user_id,
                content = excluded.content,
                updated_at = excluded.updated_at;
            """

            # Execute via runtime abstraction
            python_code = (
                "import sqlite3; "
                f"conn = sqlite3.connect('{WEBUI_DB_PATH}', timeout=30); "
                f"conn.execute('PRAGMA busy_timeout = {SQLITE_IMPORT_BUSY_TIMEOUT_MS}'); "
                "cursor = conn.cursor(); "
                f"cursor.execute({repr(sql)}); "
                "conn.commit(); "
                f"print('Imported {function_id}:', cursor.rowcount); "
                "conn.close()"
            )

            delay = SQLITE_IMPORT_INITIAL_RETRY_DELAY
            for attempt in range(1, SQLITE_IMPORT_MAX_ATTEMPTS + 1):
                try:
                    result = runtime.exec_in_container(
                        container_name,
                        ["python3", "-c", python_code],
                        capture_output=True,
                        text=True,
                        timeout=SQLITE_IMPORT_EXEC_TIMEOUT_SECONDS,
                        check=False,
                    )
                except Exception as exc:
                    if (
                        attempt < SQLITE_IMPORT_MAX_ATTEMPTS
                        and _is_sqlite_retryable_error(str(exc), error=exc)
                    ):
                        time.sleep(delay)
                        delay = min(delay * 2, SQLITE_IMPORT_MAX_RETRY_DELAY)
                        continue
                    raise

                stdout = result.stdout or ""
                stderr = result.stderr or ""
                details = "\n".join(part for part in (stdout, stderr) if part).strip()

                if result.returncode == 0 and "Imported" in stdout:
                    imported.append(module)
                    break

                if attempt < SQLITE_IMPORT_MAX_ATTEMPTS and _is_sqlite_retryable_error(
                    details
                ):
                    time.sleep(delay)
                    delay = min(delay * 2, SQLITE_IMPORT_MAX_RETRY_DELAY)
                    continue

                if details:
                    console.print(f"[warn]Failed to import {function_id}: {details}[/]")
                else:
                    console.print(
                        f"[warn]Failed to import {function_id}: exit code {result.returncode}[/]"
                    )
                break

        except Exception as e:
            console.print(f"[error]Error importing {module.path.name}: {e}[/]")

    return imported
