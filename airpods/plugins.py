"""Plugin management utilities for Open WebUI."""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from airpods.logging import console
from airpods.paths import detect_repo_root
from airpods.state import volumes_dir

SQLITE_LOCK_MARKERS = (
    "database is locked",
    "database table is locked",
    "sqlite_busy",
)
SQLITE_IMPORT_MAX_ATTEMPTS = 6
SQLITE_IMPORT_INITIAL_RETRY_DELAY = 0.25
SQLITE_IMPORT_MAX_RETRY_DELAY = 2.0
SQLITE_IMPORT_EXEC_TIMEOUT_SECONDS = 35
PLUGIN_MANIFEST_NAME = ".airpods-open-webui-plugins.json"
PLUGIN_MANIFEST_VERSION = 1


@dataclass(frozen=True)
class PluginModule:
    """Container for plugin metadata used during imports/listing."""

    id: str
    legacy_id: str
    path: Path
    content: str
    function_type: str
    name: str
    description: str
    manifest: dict


@dataclass
class PluginImportResult:
    """Summary of a best-effort Open WebUI function import."""

    modules: list[PluginModule]
    created: int = 0
    updated: int = 0
    migrated: int = 0
    unchanged: int = 0
    failed: int = 0

    @property
    def succeeded(self) -> int:
        return self.created + self.updated + self.migrated + self.unchanged


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
    """Generate an identifier-safe, namespaced Open WebUI function ID."""
    rel_no_suffix = plugin_path.relative_to(base_dir).with_suffix("")
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", rel_no_suffix.as_posix())
    normalized = re.sub(r"_+", "_", normalized).strip("_").lower()
    return f"airpods_{normalized}"


def _legacy_plugin_id_for_path(base_dir: Path, plugin_path: Path) -> str:
    rel_no_suffix = plugin_path.relative_to(base_dir).with_suffix("")
    return rel_no_suffix.as_posix().replace("/", ".")


def _detect_function_type(content: str) -> str | None:
    """Identify supported top-level Open WebUI function classes."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return None
    class_names = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    for class_name, function_type in (
        ("Pipe", "pipe"),
        ("Filter", "filter"),
        ("Action", "action"),
        ("Event", "event"),
    ):
        if class_name in class_names:
            return function_type
    return None


def _plugin_frontmatter(content: str) -> dict[str, str]:
    """Read simple key/value metadata from a module docstring."""
    try:
        docstring = ast.get_docstring(ast.parse(content), clean=False) or ""
    except SyntaxError:
        return {}
    metadata: dict[str, str] = {}
    for line in docstring.splitlines():
        key, separator, value = line.partition(":")
        if separator and re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]*", key.strip()):
            metadata[key.strip().lower()] = value.strip()
    return metadata


def _discover_function_plugins(
    base_dir: Path, relative_paths: set[Path] | None = None
) -> list[PluginModule]:
    """Return modules exposing current Open WebUI function classes."""

    if not base_dir.exists():
        return []

    modules: list[PluginModule] = []
    plugin_files = (
        [base_dir / path for path in sorted(relative_paths)]
        if relative_paths is not None
        else sorted(base_dir.rglob("*.py"))
    )
    seen_ids: set[str] = set()
    for plugin_file in plugin_files:
        if plugin_file.name == "__init__.py" or plugin_file.name.startswith("_"):
            continue
        try:
            content = plugin_file.read_text(encoding="utf-8")
        except OSError as exc:
            console.print(f"[warn]Unable to read plugin file {plugin_file}: {exc}[/]")
            continue

        try:
            ast.parse(content)
        except SyntaxError as exc:
            console.print(f"[warn]Invalid plugin syntax in {plugin_file}: {exc}[/]")
            continue
        function_type = _detect_function_type(content)
        if function_type is None:
            continue

        plugin_id = _plugin_id_for_path(base_dir, plugin_file)
        if plugin_id in seen_ids:
            console.print(
                f"[warn]Duplicate generated plugin ID {plugin_id}; skipping {plugin_file}[/]"
            )
            continue
        seen_ids.add(plugin_id)
        metadata = _plugin_frontmatter(content)
        modules.append(
            PluginModule(
                id=plugin_id,
                legacy_id=_legacy_plugin_id_for_path(base_dir, plugin_file),
                path=plugin_file,
                content=content,
                function_type=function_type,
                name=metadata.get("title")
                or plugin_file.stem.replace("_", " ").title(),
                description=metadata.get("description", ""),
                manifest=metadata,
            )
        )

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
        force: If True, overwrite managed targets even when content is identical.
        prune: If True, remove only files tracked by the previous manifest and no
            longer bundled. Unmanaged user files are always preserved.

    Returns:
        Number of plugins synced.
    """
    source_dir = get_plugins_source_dir()
    target_dir = get_plugins_target_dir()

    if not source_dir.exists():
        console.print(f"[warn]Plugin source directory not found: {source_dir}[/]")
        return 0

    target_dir.mkdir(parents=True, exist_ok=True)

    plugin_files = sorted(
        p
        for p in source_dir.rglob("*.py")
        if p.name != "__init__.py" and not p.name.startswith("_")
    )
    manifest_path = target_dir / PLUGIN_MANIFEST_NAME
    previous_files: dict[str, str] = {}
    if manifest_path.exists():
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
            if previous.get("version") == PLUGIN_MANIFEST_VERSION and isinstance(
                previous.get("files"), dict
            ):
                previous_files = previous["files"]
            else:
                console.print(
                    f"[warn]Ignoring unsupported plugin manifest: {manifest_path}[/]"
                )
        except (OSError, json.JSONDecodeError, AttributeError):
            console.print(f"[warn]Ignoring invalid plugin manifest: {manifest_path}[/]")

    synced = 0
    managed_files: dict[str, str] = {}

    for plugin_file in plugin_files:
        relative = plugin_file.relative_to(source_dir)
        relative_name = relative.as_posix()
        source_bytes = plugin_file.read_bytes()
        digest = hashlib.sha256(source_bytes).hexdigest()
        managed_files[relative_name] = digest
        target_file = target_dir / relative
        target_file.parent.mkdir(parents=True, exist_ok=True)
        should_copy = force or not target_file.exists()
        if not should_copy:
            should_copy = hashlib.sha256(target_file.read_bytes()).hexdigest() != digest
        if should_copy:
            shutil.copy2(plugin_file, target_file)
            synced += 1

    if prune:
        for relative_name in previous_files.keys() - managed_files.keys():
            relative = Path(relative_name)
            if relative.is_absolute() or ".." in relative.parts:
                continue
            stale = target_dir / relative
            if stale.is_file():
                stale.unlink()

    manifest = {"version": PLUGIN_MANIFEST_VERSION, "files": managed_files}
    manifest_content = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if (
        not manifest_path.exists()
        or manifest_path.read_text(encoding="utf-8") != manifest_content
    ):
        temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
        temporary.write_text(manifest_content, encoding="utf-8")
        temporary.replace(manifest_path)

    return synced


def managed_plugin_paths(target_dir: Path | None = None) -> set[Path]:
    """Return safe plugin paths owned by the current Airpods sync manifest."""
    directory = target_dir or get_plugins_target_dir()
    manifest_path = directory / PLUGIN_MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if manifest.get("version") != PLUGIN_MANIFEST_VERSION or not isinstance(
        manifest.get("files"), dict
    ):
        return set()
    paths = {Path(name) for name in manifest["files"]}
    return {path for path in paths if not path.is_absolute() and ".." not in path.parts}


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
    if result.returncode != 0:
        detail = (result.stderr or "").strip()
        if detail:
            console.print(f"[warn]Unable to query Open WebUI admin user: {detail}[/]")
        return None
    admin_id = (result.stdout or "").strip()
    return admin_id or None


def resolve_plugin_owner_user_id(
    runtime, container_name: str, mode: str = "auto"
) -> str:
    """Resolve which WebUI user id should own imported plugins.

    - auto: use an existing admin if possible, otherwise use ``system``.
    - admin: only use an existing admin, else fall back to 'system'.
    - airpods: legacy mode that falls back to ``system``.

    Account creation is intentionally left to Open WebUI.
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

    if normalized == "airpods":
        console.print(
            "[warn]cli.plugin_owner='airpods' is legacy behavior; plugins will be owned by 'system'.[/]"
        )

    return "system"


_IMPORT_PLUGIN_SCRIPT = r"""
import base64
import json
import sqlite3
import sys
import time

DB_PATH = "/app/backend/data/webui.db"
payload = json.loads(base64.b64decode(sys.argv[1]).decode())
conn = sqlite3.connect(DB_PATH, timeout=30)
conn.execute("PRAGMA busy_timeout = 30000")

def tables():
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

def columns(table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}

def replace_json_reference(table, column, old, new):
    if table not in tables() or column not in columns(table):
        return
    def replace(value):
        if isinstance(value, dict):
            return {
                (new if key == old else key): replace(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [replace(item) for item in value]
        return new if value == old else value
    for row_id, raw in conn.execute(f"SELECT id, {column} FROM {table}").fetchall():
        if not raw:
            continue
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        updated = replace(value)
        if updated != value:
            conn.execute(
                f"UPDATE {table} SET {column}=? WHERE id=?",
                (json.dumps(updated), row_id),
            )

required = {
    "id", "user_id", "name", "type", "content", "meta",
    "created_at", "updated_at", "is_active", "is_global",
}
if "function" not in tables() or not required.issubset(columns("function")):
    raise RuntimeError("unsupported Open WebUI function table schema")

canonical = payload["id"]
legacy = payload["legacy_id"]
now = int(time.time())
conn.execute("BEGIN IMMEDIATE")
try:
    current = conn.execute("SELECT id FROM function WHERE id=?", (canonical,)).fetchone()
    old = None
    if legacy != canonical:
        old = conn.execute("SELECT id FROM function WHERE id=?", (legacy,)).fetchone()
    if current and old:
        raise RuntimeError(
            f"both canonical and legacy function IDs exist: {canonical}, {legacy}"
        )

    migrated = bool(old and not current)
    if migrated:
        conn.execute("UPDATE function SET id=? WHERE id=?", (canonical, legacy))
        if "function_history" in tables() and "function_id" in columns("function_history"):
            conn.execute(
                "UPDATE function_history SET function_id=? WHERE function_id=?",
                (canonical, legacy),
            )
        for table, column in (("user", "settings"), ("users", "settings"), ("model", "meta")):
            replace_json_reference(table, column, legacy, canonical)

    existing = conn.execute(
        "SELECT user_id, name, type, content, meta FROM function WHERE id=?",
        (canonical,),
    ).fetchone()
    existing_meta = {}
    if existing and existing[4]:
        try:
            existing_meta = json.loads(existing[4])
        except (TypeError, json.JSONDecodeError):
            existing_meta = {}
    if not isinstance(existing_meta, dict):
        existing_meta = {}
    stored_meta_json = json.dumps(existing_meta, sort_keys=True)
    existing_meta.update(payload["meta"])
    meta_json = json.dumps(existing_meta, sort_keys=True)
    desired = (
        payload["user_id"], payload["name"], payload["type"],
        payload["content"], meta_json,
    )

    if existing is None:
        conn.execute(
            "INSERT INTO function "
            "(id, user_id, name, type, content, meta, created_at, updated_at, is_active, is_global) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0)",
            (canonical, *desired, now, now),
        )
        status = "created"
    elif tuple(existing[:4]) + (stored_meta_json,) == desired:
        status = "migrated" if migrated else "unchanged"
    else:
        conn.execute(
            "UPDATE function SET user_id=?, name=?, type=?, content=?, meta=?, updated_at=? "
            "WHERE id=?",
            (*desired, now, canonical),
        )
        status = "migrated" if migrated else "updated"
    conn.commit()
except Exception:
    conn.rollback()
    raise
finally:
    conn.close()
print(json.dumps({"status": status, "id": canonical}))
"""


def import_plugins_to_webui(
    runtime,
    plugins_dir: Path,
    admin_user_id: str = "system",
    container_name: str = "open-webui-0",
    managed_paths: set[Path] | None = None,
) -> PluginImportResult:
    """Import managed functions into Open WebUI's SQLite database.

    Updates preserve Open WebUI-managed columns such as valves, activation,
    global visibility, and creation time. Legacy dotted Airpods IDs are
    migrated transactionally with known JSON references.

    Args:
        runtime: Container runtime instance
        plugins_dir: Directory containing plugin .py files
        admin_user_id: User ID to assign as owner (default: "system")
        container_name: Name of the Open WebUI container

    Returns:
        A categorized best-effort import summary.
    """
    if not plugins_dir.exists():
        console.print(f"[warn]Plugins directory not found: {plugins_dir}[/]")
        return PluginImportResult([])

    paths = (
        managed_paths
        if managed_paths is not None
        else managed_plugin_paths(plugins_dir)
    )
    modules = _discover_function_plugins(plugins_dir, paths)
    summary = PluginImportResult([])

    for module in modules:
        try:
            rel_display = module.path.relative_to(plugins_dir).as_posix()
            payload = {
                "id": module.id,
                "legacy_id": module.legacy_id,
                "user_id": admin_user_id,
                "name": module.name,
                "type": module.function_type,
                "content": module.content,
                "meta": {
                    "description": module.description
                    or f"Managed by Airpods from {rel_display}",
                    "manifest": module.manifest,
                    "airpods_managed": True,
                    "airpods_source": rel_display,
                },
            }
            encoded_payload = base64.b64encode(json.dumps(payload).encode()).decode()

            delay = SQLITE_IMPORT_INITIAL_RETRY_DELAY
            for attempt in range(1, SQLITE_IMPORT_MAX_ATTEMPTS + 1):
                try:
                    result = runtime.exec_in_container(
                        container_name,
                        ["python3", "-c", _IMPORT_PLUGIN_SCRIPT, encoded_payload],
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

                if result.returncode == 0:
                    try:
                        response = json.loads(stdout.strip())
                        status = response["status"]
                        if status not in {
                            "created",
                            "updated",
                            "migrated",
                            "unchanged",
                        }:
                            raise ValueError("unknown status")
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                        details = "invalid importer response"
                    else:
                        setattr(summary, status, getattr(summary, status) + 1)
                        summary.modules.append(module)
                        break

                if attempt < SQLITE_IMPORT_MAX_ATTEMPTS and _is_sqlite_retryable_error(
                    details
                ):
                    time.sleep(delay)
                    delay = min(delay * 2, SQLITE_IMPORT_MAX_RETRY_DELAY)
                    continue

                if details:
                    console.print(f"[warn]Failed to import {module.id}: {details}[/]")
                else:
                    console.print(
                        f"[warn]Failed to import {module.id}: exit code {result.returncode}[/]"
                    )
                summary.failed += 1
                break

        except Exception as exc:
            summary.failed += 1
            console.print(f"[error]Error importing {module.path.name}: {exc}[/]")

    return summary
