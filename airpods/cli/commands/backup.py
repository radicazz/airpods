"""Backup and restore commands for airpods state."""

from __future__ import annotations

import datetime as _dt
from contextlib import closing
import json
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import typer

from airpods import __version__ as AIRPODS_VERSION
from airpods.logging import console
from airpods.state import configs_dir, volumes_dir

from ..common import (
    COMMAND_CONTEXT,
    ensure_runtime_available,
    manager,
    resolve_services,
)
from ..help import command_help_option, maybe_show_command_help
from ..type_defs import CommandMap

BACKUP_PREFIX = "airpods-backup"
BACKUP_ROOT = "airpods_backup"
BACKUP_PATHS = {
    "config": Path("configs"),
    "webui_db": Path("webui") / "webui.db",
    "webui_dump": Path("webui") / "webui_dump.sql",
    "webui_plugins": Path("webui") / "plugins",
    "ollama_models": Path("ollama") / "models.json",
    "gguf_metadata": Path("gguf") / "metadata",
    "manifest": Path("manifest.json"),
}

OLLAMA_VOLUME = "airpods_ollama_data"
WEBUI_VOLUME = "airpods_webui_data"
GGUF_VOLUME = "airpods_models"


class BackupError(RuntimeError):
    """Raised when a backup step fails."""


class RestoreError(RuntimeError):
    """Raised when a restore step fails."""


def _timestamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def _default_archive_name() -> str:
    return f"{BACKUP_PREFIX}-{_timestamp()}.tar.gz"


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _resolve_service(name: str):
    try:
        specs = resolve_services([name])
        return specs[0] if specs else None
    except (typer.BadParameter, IndexError):
        return None


def _run_runtime_exec(
    runtime, container: str, command: List[str], timeout: int = 60
) -> subprocess.CompletedProcess[str]:
    """Execute a command in a container using the runtime abstraction."""
    try:
        return runtime.exec_in_container(
            container,
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
        )
    except Exception as exc:
        raise BackupError(f"Runtime exec failed: {exc}") from exc


def _copytree(src: Path, dest: Path) -> None:
    if not src.exists():
        return
    shutil.copytree(src, dest, dirs_exist_ok=True)


def _copytree_filtered(src: Path, dest: Path, *, exclude_suffixes: set[str]) -> None:
    if not src.exists():
        return
    for path in src.rglob("*"):
        if path.is_dir():
            continue
        if path.suffix.lower() in exclude_suffixes:
            continue
        rel = path.relative_to(src)
        target = dest / rel
        _ensure_dir(target.parent)
        shutil.copy2(path, target)


def _collect_config_dir(staging_dir: Path) -> bool:
    src = configs_dir()
    dest = staging_dir / BACKUP_PATHS["config"]
    if not src.exists():
        console.print("[warn]No configs directory found; skipping[/]")
        return False
    _copytree(src, dest)
    return True


def _collect_webui_db(staging_dir: Path) -> bool:
    src = volumes_dir() / WEBUI_VOLUME / "webui.db"
    if not src.exists():
        console.print("[warn]Open WebUI database not found; skipping raw copy[/]")
        return False
    dest = staging_dir / BACKUP_PATHS["webui_db"]
    _ensure_dir(dest.parent)
    _snapshot_sqlite(src, dest)
    return True


def _snapshot_sqlite(src: Path, dest: Path) -> None:
    try:
        with closing(
            sqlite3.connect(src.resolve().as_uri() + "?mode=ro", uri=True)
        ) as source:
            with closing(sqlite3.connect(dest)) as target:
                source.backup(target)
                if target.execute("PRAGMA quick_check").fetchone() != ("ok",):
                    raise RestoreError("SQLite database integrity check failed")
    except sqlite3.Error as exc:
        raise RestoreError(f"Invalid SQLite database: {exc}") from exc


def _dump_webui_db(
    runtime, staging_dir: Path, sql_dump: bool, container: Optional[str]
) -> bool:
    snapshot = staging_dir / BACKUP_PATHS["webui_db"]
    if not sql_dump or not snapshot.exists():
        return False
    dest = staging_dir / BACKUP_PATHS["webui_dump"]
    _ensure_dir(dest.parent)
    with closing(sqlite3.connect(snapshot)) as connection:
        dest.write_text("\n".join(connection.iterdump()), encoding="utf-8")
    return True


def _collect_webui_plugins(staging_dir: Path) -> bool:
    src = volumes_dir() / "webui_plugins"
    if not src.exists():
        console.print("[info]No custom Open WebUI plugins present; skipping[/]")
        return False
    dest = staging_dir / BACKUP_PATHS["webui_plugins"]
    _copytree(src, dest)
    return True


def _collect_gguf_metadata(staging_dir: Path) -> bool:
    src = volumes_dir() / GGUF_VOLUME / "gguf"
    if not src.exists():
        console.print("[info]No GGUF metadata found; skipping[/]")
        return False
    dest = staging_dir / BACKUP_PATHS["gguf_metadata"]
    _copytree_filtered(src, dest, exclude_suffixes={".gguf"})
    return True


def _query_ollama_models(
    runtime, container: Optional[str]
) -> Optional[List[Dict[str, Any]]]:
    if not container:
        return None
    try:
        result = _run_runtime_exec(
            runtime, container, ["ollama", "list", "--json"], timeout=60
        )
    except BackupError:
        return None
    data = result.stdout.strip()
    if not data:
        return None
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict) and "models" in parsed:
        models = parsed["models"]
    elif isinstance(parsed, list):
        models = parsed
    else:
        return None
    if not isinstance(models, list):
        return None
    return models


def _scan_ollama_manifests() -> List[Dict[str, Any]]:
    manifests_root = volumes_dir() / OLLAMA_VOLUME / "models" / "manifests"
    models: List[Dict[str, Any]] = []
    if not manifests_root.exists():
        return models
    for path in manifests_root.rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        model_entry = {
            "name": data.get("model") or data.get("name") or path.stem,
            "digest": data.get("digest") or data.get("id"),
            "size": data.get("size"),
            "modified_at": data.get("modified_at") or data.get("modifiedAt"),
            "parameters": data.get("parameters"),
            "license": data.get("license"),
            "source": data.get("source"),
        }
        models.append(model_entry)
    return models


def _collect_ollama_models(
    runtime, staging_dir: Path, container: Optional[str]
) -> List[Dict[str, Any]]:
    models = _query_ollama_models(runtime, container)
    if models is None:
        models = _scan_ollama_manifests()
    dest = staging_dir / BACKUP_PATHS["ollama_models"]
    _ensure_dir(dest.parent)
    dest.write_text(json.dumps({"models": models}, indent=2), encoding="utf-8")
    return models


def _extract_image_tag(image: str) -> str:
    if ":" in image:
        return image.split(":", 1)[1]
    return "latest"


def _inspect_image_version(image: str) -> Optional[str]:
    # TODO: Implement runtime-aware image inspection if needed
    # For now, version labels are not critical for backups
    return None


def _service_manifest(spec: Optional[Any]) -> Dict[str, Any]:
    if spec is None:
        return {}
    version = _inspect_image_version(spec.image)
    return {
        "image": spec.image,
        "image_tag": _extract_image_tag(spec.image),
        "container": spec.container,
        "version_label": version,
    }


def _write_manifest(staging_dir: Path, manifest: Dict[str, Any]) -> None:
    dest = staging_dir / BACKUP_PATHS["manifest"]
    _ensure_dir(dest.parent)
    dest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _create_archive(staging_dir: Path, output_path: Path) -> None:
    _ensure_dir(output_path.parent)
    with tarfile.open(output_path, "w:gz") as tar:
        tar.add(staging_dir, arcname=BACKUP_ROOT)


def _safe_extractall(tar: tarfile.TarFile, target: Path) -> None:
    """Conservative fallback for interpreters without extraction filters."""
    target_path = target.resolve()
    members = tar.getmembers()
    for member in members:
        destination = (target_path / member.name).resolve()
        if (
            Path(member.name).is_absolute()
            or ".." in Path(member.name).parts
            or "\\" in member.name
            or not destination.is_relative_to(target_path)
            or not (member.isfile() or member.isdir())
        ):
            raise RestoreError(f"Unsafe archive member: {member.name}")
    for member in members:
        destination = target_path / member.name
        if member.isdir():
            destination.mkdir(parents=True, exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as source, destination.open("wb") as dest:
                shutil.copyfileobj(source, dest)
            destination.chmod(member.mode & 0o777)


def _extract_archive(archive: Path, target: Path) -> Path:
    try:
        with tarfile.open(archive, "r:*") as tar:
            if hasattr(tarfile, "data_filter"):
                tar.extractall(target, filter="data")
            else:
                _safe_extractall(tar, target)
    except (tarfile.TarError, OSError) as exc:
        raise RestoreError(f"Failed to extract archive: {exc}") from exc
    root = target / BACKUP_ROOT
    if root.exists():
        return root
    entries = list(target.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    raise RestoreError("Unexpected archive layout; missing airpods_backup root")


def _load_manifest(root: Path) -> Dict[str, Any]:
    manifest_path = root / BACKUP_PATHS["manifest"]
    if not manifest_path.exists():
        console.print("[warn]Backup manifest missing; proceeding without metadata[/]")
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        console.print("[warn]Unable to parse manifest.json; continuing[/]")
        return {}


def _backup_existing_path(path: Path) -> Optional[Path]:
    if not path.exists():
        return None
    backup_path = path.with_name(path.name + f".backup.{_timestamp()}")
    if path.is_dir():
        shutil.copytree(path, backup_path)
    else:
        _ensure_dir(backup_path.parent)
        if path.suffix == ".db":
            _snapshot_sqlite(path, backup_path)
        else:
            shutil.copy2(path, backup_path)
    console.print(f"[info]Existing {path} backed up to {backup_path}")
    return backup_path


def _restore_configs(src: Path, backup_existing: bool) -> bool:
    if not src.exists():
        console.print("[info]Backup did not include configs; skipping[/]")
        return False
    dest = configs_dir()
    if backup_existing and dest.exists() and any(dest.iterdir()):
        _backup_existing_path(dest)
    _copytree(src, dest)
    console.print(f"[ok]Configs restored to {dest}")
    return True


def _hydrate_sqlite_from_dump(dump_path: Path, dest: Path) -> None:
    with closing(sqlite3.connect(dest)) as conn:
        conn.executescript(dump_path.read_text(encoding="utf-8"))
        conn.commit()
        if conn.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise RestoreError("SQLite database integrity check failed")


def _assert_webui_stopped() -> None:
    from airpods.configuration import get_config

    service = get_config().services.get("open-webui")
    if service:
        inspected = manager.runtime.container_inspect(service.container) or {}
        state = inspected.get("State") or {}
        if state.get("Running") is True or state.get("Status") in {
            "running",
            "restarting",
            "paused",
        }:
            raise RestoreError(
                "Stop Open WebUI before restoring its database: airpods stop open-webui (or use --skip-db)"
            )


def _restore_webui_db(root: Path, backup_existing: bool) -> bool:
    raw_db = root / BACKUP_PATHS["webui_db"]
    dump = root / BACKUP_PATHS["webui_dump"]
    if not raw_db.exists() and not dump.exists():
        console.print("[info]No Open WebUI database found in backup; skipping[/]")
        return False
    _assert_webui_stopped()
    dest = volumes_dir() / WEBUI_VOLUME / "webui.db"
    _ensure_dir(dest.parent)
    with tempfile.TemporaryDirectory(dir=dest.parent) as staging:
        candidate = Path(staging) / "webui.db"
        try:
            if raw_db.exists():
                _snapshot_sqlite(raw_db, candidate)
            else:
                _hydrate_sqlite_from_dump(dump, candidate)
        except (sqlite3.Error, OSError) as exc:
            raise RestoreError(f"Cannot restore database: {exc}") from exc
        if backup_existing:
            _backup_existing_path(dest)
        _assert_webui_stopped()
        candidate.replace(dest)
        for suffix in ("-wal", "-shm"):
            Path(str(dest) + suffix).unlink(missing_ok=True)
    console.print(f"[ok]Open WebUI database restored to {dest}")
    return True


def _restore_webui_plugins(root: Path) -> bool:
    src = root / BACKUP_PATHS["webui_plugins"]
    if not src.exists():
        console.print("[info]No Open WebUI plugins in backup; skipping[/]")
        return False
    dest = volumes_dir() / "webui_plugins"
    _copytree(src, dest)
    console.print(f"[ok]Open WebUI plugins restored to {dest}")
    return True


def _restore_gguf_metadata(root: Path) -> bool:
    src = root / BACKUP_PATHS["gguf_metadata"]
    if not src.exists():
        console.print("[info]No GGUF metadata in backup; skipping[/]")
        return False
    dest = volumes_dir() / GGUF_VOLUME / "gguf"
    _copytree(src, dest)
    console.print(f"[ok]GGUF metadata restored to {dest}")
    return True


def _restore_ollama_metadata(root: Path) -> Optional[Path]:
    src = root / BACKUP_PATHS["ollama_models"]
    if not src.exists():
        console.print("[info]No Ollama metadata in backup; skipping[/]")
        return None
    dest_dir = configs_dir() / "restores"
    _ensure_dir(dest_dir)
    dest = dest_dir / f"ollama_models.{_timestamp()}.json"
    shutil.copy2(src, dest)
    console.print(f"[ok]Ollama model metadata saved to {dest}")
    return dest


def _persist_manifest_copy(manifest: Dict[str, Any]) -> Optional[Path]:
    if not manifest:
        return None
    dest_dir = configs_dir() / "restores"
    _ensure_dir(dest_dir)
    dest = dest_dir / f"manifest.{_timestamp()}.json"
    dest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    console.print(f"[info]Backup manifest copied to {dest}")
    return dest


def register(app: typer.Typer) -> CommandMap:
    @app.command(context_settings=COMMAND_CONTEXT)
    def backup(
        ctx: typer.Context,
        help_: bool = command_help_option(),
        destination: Optional[Path] = typer.Option(
            None,
            "--dest",
            help="Directory where the backup archive will be written.",
        ),
        filename: Optional[str] = typer.Option(
            None,
            "--filename",
            help="Override the default archive name.",
        ),
        sql_dump: bool = typer.Option(
            True,
            "--sql-dump/--no-sql-dump",
            help="Include a SQL dump from the consistent database snapshot.",
        ),
    ) -> None:
        """Create a portable archive containing configs, DBs, and metadata."""

        maybe_show_command_help(ctx, help_)
        ensure_runtime_available()

        dest_dir = destination or Path.cwd()
        _ensure_dir(dest_dir)
        archive_name = filename or _default_archive_name()
        output_path = dest_dir / archive_name

        webui_spec = _resolve_service("open-webui")
        ollama_spec = _resolve_service("ollama")
        llamacpp_spec = _resolve_service("llamacpp")

        with tempfile.TemporaryDirectory() as tmp:
            staging_dir = Path(tmp)
            console.print("[info]Collecting configuration files...")
            config_included = _collect_config_dir(staging_dir)

            console.print("[info]Collecting Open WebUI database...")
            db_included = _collect_webui_db(staging_dir)

            dump_included = _dump_webui_db(
                manager.runtime,
                staging_dir,
                sql_dump=sql_dump,
                container=webui_spec.container if webui_spec else None,
            )

            console.print("[info]Collecting Open WebUI plugins...")
            plugins_included = _collect_webui_plugins(staging_dir)

            console.print("[info]Collecting Ollama model metadata (names/ids/urls)...")
            models = _collect_ollama_models(
                manager.runtime,
                staging_dir,
                container=ollama_spec.container if ollama_spec else None,
            )

            console.print("[info]Collecting GGUF metadata (non-model files)...")
            gguf_included = _collect_gguf_metadata(staging_dir)

            manifest = {
                "airpods_version": AIRPODS_VERSION,
                "created_at": _dt.datetime.now().isoformat(),
                "services": {
                    "open-webui": _service_manifest(webui_spec),
                    "ollama": _service_manifest(ollama_spec),
                    "llamacpp": _service_manifest(llamacpp_spec),
                },
                "components": {
                    "configs": config_included,
                    "webui_db": db_included,
                    "webui_dump": dump_included,
                    "webui_plugins": plugins_included,
                    "ollama_models_count": len(models),
                    "gguf_metadata": gguf_included,
                    "models_metadata_only": True,
                },
                "notes": {
                    "models": "Only metadata captured; re-pull binaries after restore.",
                },
            }

            console.print("[info]Writing manifest...")
            _write_manifest(staging_dir, manifest)

            console.print(f"[info]Creating archive at {output_path}...")
            _create_archive(staging_dir, output_path)

        console.print(f"[ok]Backup created: {output_path}")

    @app.command(context_settings=COMMAND_CONTEXT)
    def restore(
        ctx: typer.Context,
        help_: bool = command_help_option(),
        archive: Path = typer.Argument(
            ..., help="Path to a backup archive created by airpods."
        ),
        backup_existing: bool = typer.Option(
            True,
            "--backup-existing/--no-backup-existing",
            help="Backup current configs/DB before overwriting.",
        ),
        skip_configs: bool = typer.Option(
            False,
            "--skip-configs",
            help="Do not restore configuration files.",
        ),
        skip_db: bool = typer.Option(
            False,
            "--skip-db",
            help="Do not restore the Open WebUI database.",
        ),
        skip_plugins: bool = typer.Option(
            False,
            "--skip-plugins",
            help="Do not restore Open WebUI plugins.",
        ),
        skip_models: bool = typer.Option(
            False,
            "--skip-models",
            help="Do not restore Ollama metadata JSON.",
        ),
    ) -> None:
        """Restore configs, DB, and metadata from a backup archive."""

        maybe_show_command_help(ctx, help_)
        ensure_runtime_available()

        archive_path = archive.expanduser().resolve()
        if not archive_path.exists():
            console.print(f"[error]Backup archive not found: {archive_path}")
            raise typer.Exit(code=1)

        with tempfile.TemporaryDirectory() as tmp:
            root = _extract_archive(archive_path, Path(tmp))
            manifest = _load_manifest(root)

            if not skip_db and (
                (root / BACKUP_PATHS["webui_db"]).exists()
                or (root / BACKUP_PATHS["webui_dump"]).exists()
            ):
                _assert_webui_stopped()
            if not skip_configs:
                _restore_configs(root / BACKUP_PATHS["config"], backup_existing)
            if not skip_db:
                _restore_webui_db(root, backup_existing)
            if not skip_plugins:
                _restore_webui_plugins(root)
            _restore_gguf_metadata(root)
            metadata_path = None
            if not skip_models:
                metadata_path = _restore_ollama_metadata(root)
            manifest_copy = _persist_manifest_copy(manifest)

        console.print("[ok]Restore complete!")
        console.print(
            "[info]Next steps: re-pull any needed Ollama models based on metadata and run 'airpods start'."
        )
        if metadata_path:
            console.print(f"[info]Model metadata saved at {metadata_path}")
        if manifest_copy:
            console.print(f"[info]Manifest copy stored at {manifest_copy}")

    return {"backup": backup, "restore": restore}
