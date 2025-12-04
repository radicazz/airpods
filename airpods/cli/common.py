from __future__ import annotations

from typing import Optional

import typer

from airpods import __version__, podman
from airpods.config import REGISTRY
from airpods.configuration import get_config
from airpods.logging import console
from airpods.services import ServiceManager, ServiceSpec, UnknownServiceError, VolumeEnsureResult

HELP_OPTION_NAMES = ("-h", "--help")
COMMAND_CONTEXT = {"help_option_names": []}

_CONFIG = get_config()

DEFAULT_STOP_TIMEOUT = _CONFIG.cli.stop_timeout
DEFAULT_LOG_LINES = _CONFIG.cli.log_lines
DEFAULT_PING_TIMEOUT = _CONFIG.cli.ping_timeout

DOCTOR_REMEDIATIONS = {
    "podman": "Install Podman: https://podman.io/docs/installation",
    "podman-compose": "Install podman-compose (often via your package manager).",
    "uv": "Install uv: https://github.com/astral-sh/uv",
}

COMMAND_ALIASES = {
    "up": "start",
    "down": "stop",
    "ps": "status",
}

ALIAS_HELP_TEMPLATE = "[alias]Alias for {canonical}[/]"

manager = ServiceManager(
    REGISTRY,
    network_name=_CONFIG.runtime.network_name,
    restart_policy=_CONFIG.runtime.restart_policy,
    gpu_device_flag=_CONFIG.runtime.gpu_device_flag,
    required_dependencies=_CONFIG.dependencies.required,
    optional_dependencies=_CONFIG.dependencies.optional,
)


def resolve_services(names: Optional[list[str]]) -> list[ServiceSpec]:
    """Resolve names to service specs, surfacing Typer-friendly errors."""
    try:
        return manager.resolve(names)
    except UnknownServiceError as exc:  # noqa: B904
        raise typer.BadParameter(str(exc)) from exc


def ensure_podman_available() -> None:
    """Ensure Podman is available before running commands."""
    try:
        manager.ensure_podman()
    except podman.PodmanError as exc:  # pragma: no cover - interacts with system
        console.print(f"[error]{exc}[/]")
        raise typer.Exit(code=1)


def print_version() -> None:
    console.print(f"[bold]airpods[/bold] [accent]v{__version__}[/]")


def print_network_status(created: bool, network_name: str) -> None:
    """Display network creation or reuse status."""
    if created:
        console.print(f"[ok]Created network {network_name}[/]")
    else:
        console.print(f"[info]Network {network_name} already exists; reusing[/]")


def print_volume_status(results: list[VolumeEnsureResult]) -> None:
    """Display volume creation or reuse status for multiple volumes."""
    for result in results:
        label = "bind mount" if result.kind == "bind" else "volume"
        if result.created:
            console.print(f"[ok]Created {label} {result.source} -> {result.target}")
        else:
            console.print(
                f"[info]{label.capitalize()} {result.source} already exists; reusing"
            )
