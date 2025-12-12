from __future__ import annotations

import re
from typing import Optional

import typer

from airpods import __version__
import airpods.config as config_module
from airpods.configuration import get_config, reload_config
from airpods.configuration.schema import CLIConfig
from airpods.logging import console
from airpods.runtime import ContainerRuntimeError, get_runtime
from airpods.services import (
    ServiceManager,
    ServiceSpec,
    UnknownServiceError,
    VolumeEnsureResult,
)

HELP_OPTION_NAMES = ("-h", "--help")
COMMAND_CONTEXT = {"help_option_names": []}

_MANAGER: ServiceManager | None = None
_CONFIG = get_config()


def get_cli_config() -> CLIConfig:
    return _CONFIG.cli


class _ManagerProxy:
    def __getattr__(self, name: str):
        if _MANAGER is None:  # pragma: no cover - defensive guard
            raise AttributeError("manager is not initialized yet")
        return getattr(_MANAGER, name)


manager = _ManagerProxy()


def _apply_cli_config(config) -> None:
    global _CONFIG, _RUNTIME, DEFAULT_STOP_TIMEOUT, DEFAULT_LOG_LINES
    global DEFAULT_PING_TIMEOUT, DEFAULT_STARTUP_TIMEOUT
    global DEFAULT_STARTUP_CHECK_INTERVAL, _MANAGER

    _CONFIG = config
    _RUNTIME = get_runtime(_CONFIG.runtime.prefer)

    DEFAULT_STOP_TIMEOUT = _CONFIG.cli.stop_timeout
    DEFAULT_LOG_LINES = _CONFIG.cli.log_lines
    DEFAULT_PING_TIMEOUT = _CONFIG.cli.ping_timeout
    DEFAULT_STARTUP_TIMEOUT = _CONFIG.cli.startup_timeout
    DEFAULT_STARTUP_CHECK_INTERVAL = _CONFIG.cli.startup_check_interval

    _MANAGER = ServiceManager(
        config_module.REGISTRY,
        _RUNTIME,
        network_name=_CONFIG.runtime.network_name,
        network_driver=_CONFIG.runtime.network.driver,
        network_subnet=_CONFIG.runtime.network.subnet,
        network_gateway=_CONFIG.runtime.network.gateway,
        network_dns_servers=_CONFIG.runtime.network.dns_servers,
        network_ipv6=_CONFIG.runtime.network.ipv6,
        network_internal=_CONFIG.runtime.network.internal,
        restart_policy=_CONFIG.runtime.restart_policy,
        gpu_device_flag=_CONFIG.runtime.gpu_device_flag,
        required_dependencies=_CONFIG.dependencies.required,
        optional_dependencies=_CONFIG.dependencies.optional,
        skip_dependency_checks=_CONFIG.dependencies.skip_checks,
    )


_apply_cli_config(get_config())

DOCTOR_REMEDIATIONS = {
    "podman": "Install Podman: https://podman.io/docs/installation",
    "podman-compose": "Install podman-compose (often via your package manager).",
    "uv": "Install uv: https://github.com/astral-sh/uv",
}

COMMAND_ALIASES = {
    "up": "start",
    "run": "start",
    "down": "stop",
    "ps": "status",
    "info": "status",
}

ALIAS_HELP_TEMPLATE = "[alias]Alias for {canonical}[/]"


def refresh_cli_context() -> None:
    """Reload configuration, service registry, and derived CLI defaults."""
    config = reload_config()
    config_module.reload_registry(config)
    _apply_cli_config(config)


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
    except ContainerRuntimeError as exc:  # pragma: no cover - interacts with system
        console.print(f"[error]{exc}[/]")
        raise typer.Exit(code=1)


def print_version() -> None:
    console.print(f"[bold]airpods[/bold] [accent]v{__version__}[/]")


def print_network_status(
    created: bool, network_name: str, verbose: bool = True
) -> None:
    """Display network creation or reuse status, respecting verbose mode."""
    if not verbose:
        return
    if created:
        console.print(f"Network [accent]{network_name}[/]: [ok]✓ created[/]")
    else:
        console.print(f"Network [accent]{network_name}[/]: [ok]✓ exists[/]")


def print_volume_status(
    results: list[VolumeEnsureResult], verbose: bool = True
) -> None:
    """Display volume creation or reuse status for multiple volumes, respecting verbose mode."""
    if not verbose:
        return
    ordered = [r for r in results if r.kind == "volume"] + [
        r for r in results if r.kind == "bind"
    ]
    for result in ordered:
        label = "Bind" if result.kind == "bind" else "Volume"
        if result.created:
            console.print(f"{label} [accent]{result.source}[/]: [ok]✓ created[/]")
        else:
            console.print(f"{label} [accent]{result.source}[/]: [ok]✓ exists[/]")


def print_config_info(config_path: str | None, verbose: bool = True) -> None:
    """Print config information, with simpler output in non-verbose mode."""
    if config_path:
        if verbose:
            console.print(f"[info]Config file: {config_path}")
        else:
            console.print(f"Using config: [accent]{config_path}[/]")
    else:
        if verbose:
            console.print("[warn]No config file found; using built-in defaults.[/]")


def is_verbose_mode(ctx: typer.Context) -> bool:
    """Check if verbose mode is enabled from context."""
    return ctx.obj and ctx.obj.get("verbose", False)


_SIZE_PATTERN = re.compile(
    r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([KMGTP]?B)\s*$", re.IGNORECASE
)
_SIZE_MULTIPLIERS = {
    "B": 1,
    "KB": 1024,
    "MB": 1024**2,
    "GB": 1024**3,
    "TB": 1024**4,
}


def _size_label_to_bytes(size_label: Optional[str]) -> Optional[float]:
    if not size_label:
        return None
    match = _SIZE_PATTERN.match(size_label.strip())
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).upper()
    multiplier = _SIZE_MULTIPLIERS.get(unit)
    if multiplier is None:
        return None
    return value * multiplier


def format_transfer_label(
    size_label: Optional[str], elapsed_seconds: Optional[float]
) -> str:
    """Return a friendly "size @ speed" label for transfer metrics."""
    if not size_label:
        if elapsed_seconds and elapsed_seconds > 0:
            return f"{elapsed_seconds:.1f}s"
        return ""

    if not elapsed_seconds or elapsed_seconds <= 0:
        return size_label

    size_bytes = _size_label_to_bytes(size_label)
    if not size_bytes:
        return f"{size_label} ({elapsed_seconds:.1f}s)"

    megabytes = size_bytes / (1024**2)
    speed = megabytes / elapsed_seconds
    return f"{size_label} @ {speed:.1f} MB/s ({elapsed_seconds:.1f}s)"


def get_ollama_port() -> int:
    """
    Get the Ollama service port from configuration.

    Returns:
        Ollama port number (default: 11434)
    """
    # Find Ollama service in registry
    spec = config_module.REGISTRY.get("ollama")
    if spec and spec.ports and len(spec.ports) > 0:
        # ports is a list of tuples (host_port, container_port)
        return spec.ports[0][0]

    # Fallback to default
    return 11434
