from __future__ import annotations

import re
from typing import Optional

import typer

from airpods import __version__
from airpods import gpu as gpu_utils
import airpods.config as config_module
from airpods.configuration import get_config, reload_config
from airpods.configuration.schema import CLIConfig
from airpods.logging import console
from airpods.runtime import (
    ContainerRuntimeError,
    get_runtime,
)
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
    def __getattr__(self, name: str) -> object:
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

    # Compute runtime-specific dependencies and GPU flags
    runtime_name = _RUNTIME.runtime_name

    # Resolve GPU device flag (runtime-aware)
    resolved_gpu_flag = gpu_utils.get_gpu_device_flag(
        runtime_name, _CONFIG.runtime.gpu_device_flag
    )
    runtime_deps = _CONFIG.dependencies.runtime_deps.get(runtime_name, [])
    required_dependencies = _CONFIG.dependencies.required + runtime_deps

    _MANAGER = ServiceManager(
        config_module.REGISTRY,
        _RUNTIME,
        restart_policy=_CONFIG.runtime.restart_policy,
        gpu_device_flag=resolved_gpu_flag,
        required_dependencies=required_dependencies,
        optional_dependencies=_CONFIG.dependencies.optional,
        skip_dependency_checks=_CONFIG.dependencies.skip_checks,
    )


_apply_cli_config(get_config())

DOCTOR_REMEDIATIONS = {
    "podman": "Install Podman: https://podman.io/docs/installation",
    "podman-compose": "Install podman-compose (often via your package manager).",
    "docker": "Install Docker: https://docs.docker.com/get-docker/",
    "docker-compose": "Install Docker Compose: https://docs.docker.com/compose/install/",
    "uv": "Install uv: https://github.com/astral-sh/uv",
}

COMMAND_ALIASES = {
    "up": "start",
    "run": "start",
    "down": "stop",
    "ps": "status",
    "info": "status",
    "health": "doctor",
}

SERVICE_NAME_ALIASES = {
    "comfy": "comfyui",
    "comfyui": "comfyui",
    "comfy-ui": "comfyui",
    "llama": "llamacpp",
    "llama-cpp": "llamacpp",
    "llama.cpp": "llamacpp",
}

ALIAS_HELP_TEMPLATE = "[alias]Alias for {canonical}[/]"


def refresh_cli_context() -> None:
    """Reload configuration, service registry, and derived CLI defaults."""
    config = reload_config()
    config_module.reload_registry(config)
    _apply_cli_config(config)


def resolve_services(names: Optional[list[str]]) -> list[ServiceSpec]:
    """Resolve names to service specs with alias support, surfacing Typer-friendly errors."""
    if names is None:
        names = []
    normalized = []
    for name in names:
        lower_name = name.lower()
        canonical = SERVICE_NAME_ALIASES.get(lower_name, lower_name)
        normalized.append(canonical)
    try:
        return manager.resolve(normalized)
    except UnknownServiceError as exc:  # noqa: B904
        # Check if the service exists but is disabled in config.
        disabled = [
            name
            for name in normalized
            if name in _CONFIG.services and not _CONFIG.services[name].enabled
        ]
        if disabled:
            if len(disabled) == 1:
                name = disabled[0]
                message = (
                    f"service '{name}' is disabled in config. "
                    f"Set services.{name}.enabled=true to use it."
                )
            else:
                names_str = ", ".join(disabled)
                message = (
                    f"services disabled in config: {names_str}. "
                    "Enable them to use these commands."
                )
            raise typer.BadParameter(message) from exc
        raise typer.BadParameter(str(exc)) from exc


def ensure_runtime_available() -> None:
    """Ensure container runtime is available before running commands."""
    try:
        manager.ensure_runtime()
    except ContainerRuntimeError as exc:  # pragma: no cover - interacts with system
        console.print(f"[error]{exc}[/]")
        raise typer.Exit(code=1)


def ensure_podman_available() -> None:
    """Backwards-compatible alias for older call sites/tests."""
    ensure_runtime_available()


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


OLLAMA_DEFAULT_PORT = 11434


def get_ollama_port() -> int:
    """Get the Ollama service port from configuration."""
    spec = config_module.REGISTRY.get("ollama")
    if spec and spec.ports:
        return spec.ports[0][0]
    return OLLAMA_DEFAULT_PORT


def check_service_availability(service_name: str) -> tuple[bool, str]:
    """
    Check if a service is enabled in config and currently running.

    Args:
        service_name: Name of the service to check (e.g., "ollama")
                     Special value "any" checks if any services are running

    Returns:
        Tuple of (is_available, reason_if_not)
        - (True, "") if service is available
        - (False, "reason") if service is not available
    """
    # Handle special "any" case - check if any services are running
    if service_name == "any":
        try:
            pod_rows = manager.pod_status_rows() or {}
            # Check if any pod is running
            for row in pod_rows.values():
                if row.get("Status", "") == "Running":
                    return True, ""
            return False, "no services running"
        except Exception:
            return False, "no services running"

    # Check if service is in the registry (enabled in config)
    spec = config_module.REGISTRY.get(service_name)
    if not spec:
        return False, f"{service_name} service not enabled"

    # Check if the pod is actually running
    try:
        pod_rows = manager.pod_status_rows() or {}
        row = pod_rows.get(spec.pod)
        if not row:
            return False, f"{service_name} service not running"

        status = row.get("Status", "")
        if status != "Running":
            return False, f"{service_name} service not running"

        return True, ""
    except Exception:
        # If we can't check status, assume not available
        return False, f"{service_name} service status unknown"
