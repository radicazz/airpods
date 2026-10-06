"""Status view rendering for pod health, ports, and service availability.

This module handles the display logic for the `status` command, including:
- Rendering Rich tables with pod information
- HTTP health checks for running services
- Port binding resolution and URL formatting
- Enhanced status detection with image availability checks
"""

from __future__ import annotations

import http.client
import socket
import time
from functools import lru_cache
from datetime import datetime, timezone
from typing import Any, List, Optional

from airpods import ui
from airpods.logging import console
from airpods.services import ServiceSpec

from .common import get_cli_config, manager


def _format_uptime(started_at: str) -> str:
    """Format container uptime from start time string.

    Args:
        started_at: Container start time string from podman inspect

    Returns:
        Formatted uptime string (e.g., "5m", "2h", "3d")
    """
    try:
        # Parse the timestamp (podman format: "2025-12-04 06:03:42.530956537 -0500 EST")
        # Split and take the date/time part, ignore timezone for now
        parts = started_at.split()
        if len(parts) >= 2:
            dt_str = f"{parts[0]} {parts[1].split('.')[0]}"
            started = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            # Assume local time for simplicity
            now = datetime.now()
            delta = now - started

            total_seconds = int(delta.total_seconds())
            if total_seconds < 60:
                return f"{total_seconds}s"
            elif total_seconds < 3600:
                return f"{total_seconds // 60}m"
            elif total_seconds < 86400:
                return f"{total_seconds // 3600}h"
            else:
                return f"{total_seconds // 86400}d"
    except (ValueError, IndexError):
        pass
    return "-"


def _format_time_since(timestamp: str) -> str:
    """Format time since a timestamp (e.g., for 'stopped' or 'finished' times).

    Args:
        timestamp: Container timestamp string from podman inspect (e.g., FinishedAt)

    Returns:
        Formatted time string (e.g., "5m ago", "2h ago") or "-"
    """
    if not timestamp or timestamp == "0001-01-01T00:00:00Z":
        return "-"
    try:
        # Try ISO format first (more common in newer podman/docker)
        try:
            finished = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            delta = now - finished
        except (ValueError, TypeError):
            # Fall back to podman inspect format
            parts = timestamp.split()
            if len(parts) >= 2:
                dt_str = f"{parts[0]} {parts[1].split('.')[0]}"
                finished = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                now = datetime.now()
                delta = now - finished
            else:
                return "-"

        total_seconds = int(delta.total_seconds())
        if total_seconds < 60:
            return f"{total_seconds}s ago"
        elif total_seconds < 3600:
            return f"{total_seconds // 60}m ago"
        elif total_seconds < 86400:
            return f"{total_seconds // 3600}h ago"
        else:
            return f"{total_seconds // 86400}d ago"
    except (ValueError, IndexError, OSError):
        pass
    return "-"


def render_status(specs: List[ServiceSpec], *, show_legend: bool = True) -> None:
    """Render service health, failure details, and friendly URLs."""
    pod_rows = manager.pod_status_rows() or {}
    table = ui.themed_table()
    for column in ("Service", "Status", "Info"):
        table.add_column(column)
    for spec in specs:
        row = pod_rows.get(spec.pod)
        if not row:
            status = (
                "[warn]stopped"
                if manager.runtime.image_exists(spec.image)
                else "[muted]not pulled"
            )
            table.add_row(spec.name, status, "-")
            continue
        inspect = manager.runtime.container_inspect(spec.container) or {}
        state = inspect.get("State") or {}
        status = state.get("Status") or row.get("Status", "?")
        status = str(status).lower()
        port_bindings = manager.service_ports(spec)
        host_ports = collect_host_ports(spec, port_bindings)
        info = format_port_bindings(port_bindings)
        if status == "running":
            health = ping_service(spec, host_ports[0] if host_ports else None)
            table.add_row(
                spec.name,
                health if spec.health_path else "[ok]running",
                ", ".join(format_host_urls(host_ports)) or "-",
            )
            continue
        exit_code = state.get("ExitCode", 0)
        restarts = inspect.get("RestartCount", 0)
        if status in {"exited", "error", "dead"}:
            started = state.get("StartedAt")
            if exit_code:
                status = f"failed (exit {exit_code})"
            elif restarts > 3:
                status = f"crash loop ({restarts} restarts)"
            elif not started or started.startswith("0001-"):
                status = "created"
            else:
                status = "stopped"
        style = "error" if status.startswith(("failed", "crash loop")) else "warn"
        table.add_row(spec.name, f"[{style}]{status}", info or "-")
    console.print(table)
    if show_legend:
        _print_status_legend()


def _print_status_legend() -> None:
    """Print a brief status legend for user reference."""
    console.print()
    console.print("[muted]Status legend:[/]")
    console.print("  [ok]200[/] or [ok]code[/] – Service responding (green = healthy)")
    console.print("  [warn]code[/] or [warn]error[/] – Service not responding (yellow)")
    console.print("  [error]failed[/] – Container crashed or exit code != 0 (red)")
    console.print("  [muted]created[/] – Pod exists, container never started (gray)")
    console.print("  [muted]not pulled[/] – Image not downloaded yet (gray)")


def collect_host_ports(spec: ServiceSpec, port_bindings: dict[str, Any]) -> List[int]:
    """Return the list of host ports published for a service."""
    host_ports: List[int] = []
    for bindings in port_bindings.values():
        for binding in bindings or []:
            host_port = binding.get("HostPort")
            if not host_port:
                continue
            try:
                value = int(host_port)
            except (TypeError, ValueError):
                continue
            if value not in host_ports:
                host_ports.append(value)
    if not host_ports:
        for host_port, _ in spec.ports:
            if host_port not in host_ports:
                host_ports.append(host_port)
    return host_ports


def format_host_urls(host_ports: List[int]) -> List[str]:
    """Format user-friendly host URLs for each host port."""
    host = _resolve_host_ip()
    return [f"http://{host}:{port}" for port in host_ports]


@lru_cache(maxsize=1)
def _resolve_host_ip() -> str:
    """Resolve the best-effort host IP for display in status output."""
    for target in (("8.8.8.8", 80), ("1.1.1.1", 80)):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(target)
                ip = sock.getsockname()[0]
                if ip and not ip.startswith(("127.", "0.")):
                    return ip
        except OSError:
            continue
    try:
        hostname_ip = socket.gethostbyname(socket.gethostname())
        if hostname_ip and not hostname_ip.startswith(("127.", "0.")):
            return hostname_ip
    except OSError:
        pass
    return "localhost"


def format_port_bindings(port_bindings: dict[str, Any]) -> str:
    """Format port bindings for display."""
    ports: list[str] = []
    for container_port, bindings in port_bindings.items():
        for binding in bindings or []:
            host_port = binding.get("HostPort", "")
            if host_port:
                ports.append(f"{host_port}->{container_port}")
    return ", ".join(ports) if ports else "-"


def _probe_service(spec: ServiceSpec, port: Optional[int], timeout: float | None):
    if not spec.health_path or port is None:
        return None, 0.0, None
    conn = None
    start = time.perf_counter()
    try:
        conn = http.client.HTTPConnection(
            "127.0.0.1",
            port,
            timeout=timeout if timeout is not None else get_cli_config().ping_timeout,
        )
        conn.request("GET", spec.health_path)
        code = conn.getresponse().status
        return code, (time.perf_counter() - start) * 1000, None
    except (OSError, http.client.HTTPException) as exc:
        return None, 0.0, type(exc).__name__
    finally:
        if conn is not None:
            conn.close()


def ping_service(
    spec: ServiceSpec, port: Optional[int], *, timeout: float | None = None
) -> str:
    code, latency, error = _probe_service(spec, port, timeout)
    if error:
        return f"[warn]{error}"
    if code is None:
        return "-"
    low, high = spec.health_expected_status
    style = "ok" if low <= code <= high else "warn"
    return f"[{style}]{code} ({latency:.0f} ms)"


def check_service_health(
    spec: ServiceSpec, port: Optional[int], *, timeout: float | None = None
) -> bool:
    code, _, _ = _probe_service(spec, port, timeout)
    low, high = spec.health_expected_status
    return code is not None and low <= code <= high
