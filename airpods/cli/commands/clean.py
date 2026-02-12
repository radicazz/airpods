"""Clean command for removing volumes, images, configs, and user data."""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.panel import Panel
from rich.table import Table

from airpods import ui
from airpods.logging import console
from airpods.runtime import ContainerRuntimeError
from airpods.state import configs_dir, volumes_dir

from airpods import config as config_module
from ..common import (
    COMMAND_CONTEXT,
    DEFAULT_STOP_TIMEOUT,
    SERVICE_NAME_ALIASES,
    ensure_runtime_available,
    get_cli_config,
    manager,
)
from ..completions import service_name_completion
from ..help import command_help_option, maybe_show_command_help, exit_with_help
from ..type_defs import CommandMap

ensure_podman_available = ensure_runtime_available


class CleanupPlan:
    """Holds items to be cleaned up."""

    def __init__(self):
        self.pods: list[tuple[str, str]] = []  # (name, pod_name)
        self.volumes: list[str] = []
        self.bind_mounts: list[tuple[Path, int]] = []  # (path, size_bytes)
        self.images: list[tuple[str, str, int]] = []  # (name, image, size_bytes)
        self.config_files: list[Path] = []
        self.config_dirs: list[Path] = []

    def has_items(self) -> bool:
        """Check if there's anything to clean."""
        return bool(
            self.pods
            or self.volumes
            or self.bind_mounts
            or self.images
            or self.config_files
            or self.config_dirs
        )

    def total_bytes(self) -> int:
        """Calculate total bytes to be freed."""
        total = 0
        for _, size in self.bind_mounts:
            total += size
        for _, _, size in self.images:
            total += size
        return total


def _get_dir_size(path: Path) -> int:
    """Get total size of a directory in bytes."""
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                try:
                    total += os.path.getsize(filepath)
                except (OSError, FileNotFoundError):
                    pass
    except (OSError, PermissionError):
        pass
    return total


def _parse_image_size(size_str: str) -> int:
    """Parse podman image size string to bytes."""
    try:
        size_str = size_str.strip().upper()
        multipliers = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
        for unit, mult in multipliers.items():
            if size_str.endswith(unit):
                num = float(size_str[: -len(unit)])
                return int(num * mult)
    except (ValueError, AttributeError):
        pass
    return 0


def _format_bytes(bytes_count: int) -> str:
    """Format bytes to human-readable string."""
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_count < 1024.0:
            return f"{bytes_count:.1f}{unit}"
        bytes_count /= 1024.0
    return f"{bytes_count:.1f}TB"


def _resolve_cleanup_specs(names: Optional[list[str]]):
    specs = config_module.load_service_specs(include_disabled=True)
    if not names:
        return specs
    normalized = []
    for name in names:
        lower_name = name.lower()
        normalized.append(SERVICE_NAME_ALIASES.get(lower_name, lower_name))
    spec_map = {spec.name: spec for spec in specs}
    missing = [name for name in normalized if name not in spec_map]
    if missing:
        available = ", ".join(sorted(spec_map.keys()))
        raise typer.BadParameter(
            f"unknown service(s): {', '.join(missing)}. available: {available}"
        )
    return [spec_map[name] for name in normalized]


def _collect_cleanup_targets(
    *,
    specs,
    pods: bool = False,
    volumes: bool = False,
    images: bool = False,
    configs: bool = False,
    include_orphans: bool = False,
) -> CleanupPlan:
    """Scan filesystem and runtime to identify what exists and should be cleaned."""
    plan = CleanupPlan()
    service_names = {spec.name for spec in specs}

    if pods:
        for spec in specs:
            if manager.runtime.pod_exists(spec.pod):
                plan.pods.append((spec.name, spec.pod))

    if volumes:
        existing_volumes = set(manager.runtime.list_volumes())
        configured_volumes = set()
        bind_sources: set[Path] = set()
        volumes_root = volumes_dir().resolve()
        for spec in specs:
            for mount in getattr(spec, "volumes", []) or []:
                if mount.is_bind_mount:
                    source_path = Path(mount.source).resolve()
                    try:
                        source_path.relative_to(volumes_root)
                    except ValueError:
                        continue
                    bind_sources.add(source_path)
                else:
                    configured_volumes.add(mount.source)
        if include_orphans:
            prefixed_orphans = {
                name for name in existing_volumes if name.startswith("airpods_")
            }
            plan.volumes = sorted(
                prefixed_orphans.union(
                    existing_volumes.intersection(configured_volumes)
                )
            )
        else:
            plan.volumes = sorted(existing_volumes.intersection(configured_volumes))

        if include_orphans:
            if volumes_root.exists():
                for item in volumes_root.iterdir():
                    if item.is_dir():
                        bind_sources.add(item)

        for path in sorted(bind_sources):
            if not path.exists():
                continue
            size_bytes = _get_dir_size(path)
            plan.bind_mounts.append((path, size_bytes))

    if images:
        seen_images: set[str] = set()
        for spec in specs:
            images = [spec.image]
            cpu_image = getattr(spec, "cpu_image", None)
            if isinstance(cpu_image, str) and cpu_image:
                images.append(cpu_image)
            for image in filter(None, images):
                if image in seen_images:
                    continue
                seen_images.add(image)
                size_str = manager.runtime.image_size(image)
                if size_str:
                    size_bytes = _parse_image_size(size_str)
                    plan.images.append((spec.name, image, size_bytes))

    if configs:
        cfg_dir = configs_dir()
        if cfg_dir.exists():
            if include_orphans:
                for item in cfg_dir.iterdir():
                    if item.is_file():
                        plan.config_files.append(item)
                    elif item.is_dir():
                        plan.config_dirs.append(item)
            else:
                if "open-webui" in service_names:
                    secret = cfg_dir / "webui_secret"
                    if secret.exists():
                        plan.config_files.append(secret)

    return plan


def _show_cleanup_plan(plan: CleanupPlan, dry_run: bool = False) -> None:
    """Display a Rich table/panel showing what will be removed."""
    lines = []

    if dry_run:
        lines.append("[bold yellow]DRY RUN - No changes will be made[/]\n")
    lines.append("[bold]The following items will be PERMANENTLY removed:[/]\n")

    if plan.pods:
        lines.append("[cyan]Pods & Containers:[/]")
        for name, pod in plan.pods:
            lines.append(f"  • {name} ({pod})")
        lines.append("")

    if plan.volumes:
        lines.append(f"[cyan]Volumes ({len(plan.volumes)}):[/]")
        for vol in plan.volumes:
            lines.append(f"  • {vol}")
        lines.append("")

    if plan.bind_mounts:
        lines.append("[cyan]Bind Mounts:[/]")
        for mount, size_bytes in plan.bind_mounts:
            size_str = _format_bytes(size_bytes) if size_bytes > 0 else "0B"
            lines.append(f"  • {mount} ({size_str})")
        lines.append("")

    if plan.images:
        lines.append(f"[cyan]Images ({len(plan.images)}):[/]")
        for name, image, size_bytes in plan.images:
            size_str = _format_bytes(size_bytes) if size_bytes > 0 else "unknown size"
            lines.append(f"  • {image} ({size_str})")
        lines.append("")

    if plan.config_files:
        lines.append("[cyan]Config Files:[/]")
        for cfg in plan.config_files:
            lines.append(f"  • {cfg}")
        lines.append("")

    if plan.config_dirs:
        lines.append("[cyan]Config Directories:[/]")
        for cfg in plan.config_dirs:
            lines.append(f"  • {cfg}")
        lines.append("")

    panel = Panel("\n".join(lines), title="Cleanup Plan", border_style="yellow")
    console.print(panel)


def _clean_pods(plan: CleanupPlan, timeout: int) -> int:
    """Stop and remove all pods. Returns count of pods removed."""
    count = 0
    for name, pod in plan.pods:
        try:
            if manager.runtime.pod_exists(pod):
                manager.runtime.stop_pod(pod, timeout=timeout)
                manager.runtime.remove_pod(pod)
                count += 1
        except ContainerRuntimeError as exc:
            console.print(f"[warn]Failed to remove {pod}: {exc}[/]")
    return count


def _clean_volumes(plan: CleanupPlan) -> int:
    """Remove Podman volumes. Returns count removed."""
    count = 0
    for vol in plan.volumes:
        try:
            manager.runtime.remove_volume(vol)
            count += 1
        except ContainerRuntimeError as exc:
            console.print(f"[warn]Failed to remove volume {vol}: {exc}[/]")
    return count


def _clean_bind_mounts(plan: CleanupPlan) -> tuple[int, int]:
    """Remove bind mount directories. Returns (count removed, bytes freed)."""
    count = 0
    bytes_freed = 0
    for mount, size_bytes in plan.bind_mounts:
        try:
            if mount.exists():
                shutil.rmtree(mount)
                count += 1
                bytes_freed += size_bytes
        except OSError as exc:
            console.print(f"[warn]Failed to remove {mount}: {exc}[/]")
    return count, bytes_freed


def _clean_images(plan: CleanupPlan) -> tuple[int, int]:
    """Remove container images. Returns (count removed, bytes freed)."""
    count = 0
    bytes_freed = 0
    for name, image, size_bytes in plan.images:
        try:
            manager.runtime.remove_image(image)
            count += 1
            bytes_freed += size_bytes
        except ContainerRuntimeError as exc:
            console.print(f"[warn]Failed to remove image {image}: {exc}[/]")
    return count, bytes_freed


def _clean_configs(plan: CleanupPlan, backup: bool = False) -> int:
    """Remove config files. Returns count removed."""
    count = 0
    for cfg in plan.config_files:
        try:
            if backup and cfg.name == "config.toml":
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = cfg.parent / f"config.toml.backup.{timestamp}"
                shutil.copy2(cfg, backup_path)
                console.print(f"[info]Backed up config to {backup_path}[/]")

            cfg.unlink()
            count += 1
        except OSError as exc:
            console.print(f"[warn]Failed to remove {cfg}: {exc}[/]")

    for cfg_dir in sorted(plan.config_dirs, key=lambda p: len(str(p)), reverse=True):
        try:
            if cfg_dir.exists():
                shutil.rmtree(cfg_dir)
                count += 1
        except OSError as exc:
            console.print(f"[warn]Failed to remove {cfg_dir}: {exc}[/]")
    return count


def register(app: typer.Typer) -> CommandMap:
    @app.command(context_settings=COMMAND_CONTEXT)
    def clean(
        ctx: typer.Context,
        help_: bool = command_help_option(),
        service: Optional[list[str]] = typer.Argument(
            None,
            help="Services to clean (default: all).",
            metavar="service",
            shell_complete=service_name_completion,
        ),
        all_: bool = typer.Option(
            False,
            "--all",
            "-a",
            help="Remove everything (pods, volumes, images, configs).",
        ),
        pods: bool = typer.Option(
            False, "--pods", "-p", help="Stop and remove all pods and containers."
        ),
        volumes: bool = typer.Option(
            False,
            "--volumes",
            "-v",
            help="Remove Podman volumes and bind mount directories.",
        ),
        images: bool = typer.Option(
            False, "--images", "-i", help="Remove pulled container images."
        ),
        configs: bool = typer.Option(
            False,
            "--configs",
            "-c",
            help="Remove config files under configs/ (config.toml, webui_secret, caches).",
        ),
        force: bool = typer.Option(
            False, "--force", "-f", help="Skip confirmation prompts."
        ),
        dry_run: bool = typer.Option(
            False, "--dry-run", help="Show what would be deleted without deleting."
        ),
        backup_config: bool = typer.Option(
            True,
            "--backup-config/--no-backup-config",
            help="Backup config.toml before deletion.",
        ),
    ) -> None:
        """Remove volumes, images, configs, and user data created by airpods."""
        maybe_show_command_help(ctx, help_)
        force = force or get_cli_config().auto_confirm

        if all_:
            pods = volumes = images = configs = True

        if not any([pods, volumes, images, configs]):
            exit_with_help(
                ctx,
                message="No cleanup targets specified.",
                code=1,
            )

        ensure_runtime_available()

        specs = _resolve_cleanup_specs(service)
        include_orphans = service is None

        plan = _collect_cleanup_targets(
            specs=specs,
            pods=pods,
            volumes=volumes,
            images=images,
            configs=configs,
            include_orphans=include_orphans,
        )

        if not plan.has_items():
            console.print(
                "[ok]Nothing to clean - all requested items are already gone.[/]"
            )
            return

        _show_cleanup_plan(plan, dry_run=dry_run)

        if dry_run:
            console.print("\n[info]Dry run complete. No changes were made.[/]")
            return

        if not force:
            if not ui.confirm_action("Proceed with cleanup?", default=False):
                console.print("[warn]Cleanup cancelled by user.[/]")
                raise typer.Abort()

        results = Table.grid(padding=(0, 2))
        results.add_column(style="cyan")
        results.add_column()

        total_bytes_freed = 0

        if plan.pods:
            count = _clean_pods(plan, timeout=DEFAULT_STOP_TIMEOUT)
            results.add_row("Cleaning pods...", f"[ok]✓ {count} pod(s) removed[/]")

        if plan.volumes:
            count = _clean_volumes(plan)
            results.add_row(
                "Cleaning volumes...", f"[ok]✓ {count} volume(s) removed[/]"
            )

        if plan.bind_mounts:
            count, bytes_freed = _clean_bind_mounts(plan)
            total_bytes_freed += bytes_freed
            results.add_row(
                "Cleaning bind mounts...", f"[ok]✓ {count} directory(ies) removed[/]"
            )

        if plan.images:
            count, bytes_freed = _clean_images(plan)
            total_bytes_freed += bytes_freed
            results.add_row("Cleaning images...", f"[ok]✓ {count} image(s) removed[/]")

        if plan.config_files or plan.config_dirs:
            count = _clean_configs(plan, backup=backup_config)
            results.add_row("Cleaning configs...", f"[ok]✓ {count} file(s) removed[/]")

        console.print()
        console.print(results)

        if total_bytes_freed > 0:
            console.print(
                f"\n[ok]✓ Cleanup complete! Space freed: {_format_bytes(total_bytes_freed)}[/]"
            )
        else:
            console.print("\n[ok]✓ Cleanup complete![/]")

    return {"clean": clean}
