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

from .common import DEFAULT_PING_TIMEOUT, manager


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
    """Render the pod status table with enhanced state detection.

    Args:
        specs: List of service specifications to check status for.
        show_legend: Whether to print the status legend beneath the table.

    Note:
        manager.pod_status_rows() returns a dict mapping pod names to status info,
        or an empty dict if no pods are running.

        Enhanced status detection distinguishes between:
        - "not pulled": image not available locally
        - "created": pod exists but container never started
        - "stopped": container was running but is now exited
        - "degraded": running but health check failed
        - "failed": container crashed (exit code != 0)
        - running with health status
    """
    pod_rows = manager.pod_status_rows()
    if pod_rows is None:
        pod_rows = {}
    table = ui.themed_table()
    table.add_column("Service")
    table.add_column("Status")
    table.add_column("Time", justify="right")
    table.add_column("Info", no_wrap=False)

    for spec in specs:
        row = pod_rows.get(spec.pod) if pod_rows else None
        if not row:
            # Pod doesn't exist - check if image is pulled
            image_exists = manager.runtime.image_exists(spec.image)
            if not image_exists:
                table.add_row(spec.name, "[muted]not pulled", "-", "-")
            else:
                table.add_row(spec.name, "[warn]stopped", "-", "-")
            continue

        status = row.get("Status", "?")

        uptime = "-"
        finished_at = "-"
        exit_code = 0
        restart_count = 0

        inspect = manager.runtime.container_inspect(spec.container)
        if inspect and "State" in inspect:
            state = inspect["State"]
            # Get started time for running containers
            if "StartedAt" in state and state["StartedAt"]:
                uptime = _format_uptime(state["StartedAt"])
            # Get finished time for exited containers
            if "FinishedAt" in state and state["FinishedAt"]:
                finished_at = _format_time_since(state["FinishedAt"])
            # Get exit code
            exit_code = state.get("ExitCode", 0)
            # Get restart count
            restart_count = inspect.get("RestartCount", 0)

        if status == "Running":
            port_bindings = manager.service_ports(spec)
            host_ports = collect_host_ports(spec, port_bindings)
            host_port = host_ports[0] if host_ports else None
            health = ping_service(spec, host_port)
            url_text = ", ".join(format_host_urls(host_ports)) if host_ports else "-"
            table.add_row(spec.name, health, uptime, url_text)
        elif status == "Exited":
            port_bindings = manager.service_ports(spec)
            ports_display = format_port_bindings(port_bindings)

            # Determine status based on exit code and history
            if uptime == "-" or uptime == "0s":
                status_text = "[muted]created"
                time_display = "-"
            elif exit_code != 0:
                status_text = f"[error]failed (exit {exit_code})"
                time_display = finished_at if finished_at != "-" else uptime
            elif restart_count > 3:
                status_text = f"[error]crash loop ({restart_count} restarts)"
                time_display = finished_at if finished_at != "-" else "-"
            elif restart_count > 0:
                status_text = f"[warn]restarting ({restart_count})"
                time_display = finished_at if finished_at != "-" else "-"
            else:
                status_text = "[warn]stopped"
                time_display = finished_at if finished_at != "-" else uptime

            table.add_row(spec.name, status_text, time_display, ports_display)
        else:
            table.add_row(spec.name, f"[warn]{status}", uptime, "-")

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


def ping_service(
    spec: ServiceSpec, port: Optional[int], *, timeout: float | None = None
) -> str:
    """Ping a service's health endpoint and return status.

    Args:
        spec: Service specification containing health_path
        port: Host port to connect to
        timeout: Optional override for the ping timeout (falls back to CLI config / default)

    Returns:
        Formatted status string with HTTP code and latency, or error type
    """
    if not spec.health_path or port is None:
        return "-"
    ping_timeout = timeout if timeout is not None else DEFAULT_PING_TIMEOUT
    try:
        start = time.perf_counter()
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=ping_timeout)
        conn.request("GET", spec.health_path)
        resp = conn.getresponse()
        code = resp.status
        conn.close()
        elapsed_ms = (time.perf_counter() - start) * 1000
        expected_start, expected_end = spec.health_expected_status
        if expected_start <= code <= expected_end:
            return f"[ok]{code} ({elapsed_ms:.0f} ms)"
        return f"[warn]{code} ({elapsed_ms:.0f} ms)"
    except (
        socket.error,
        http.client.HTTPException,
        OSError,
        ConnectionError,
        TimeoutError,
    ) as exc:
        return f"[warn]{type(exc).__name__}"
    except Exception as exc:
        # Fallback for unexpected errors; log for debugging
        console.print(f"[dim]Unexpected error pinging {spec.name}: {exc}[/dim]")
        return f"[error]{type(exc).__name__}"


def check_service_health(
    spec: ServiceSpec, port: Optional[int], *, timeout: float | None = None
) -> bool:
    """Check if a service is healthy (returns True/False).

    Args:
        spec: Service specification containing health_path
        port: Host port to connect to
        timeout: Optional override for the ping timeout (falls back to CLI config / default)

    Returns:
        True if service is healthy (2xx-3xx response), False otherwise
    """
    if not spec.health_path or port is None:
        return False
    ping_timeout = timeout if timeout is not None else DEFAULT_PING_TIMEOUT
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=ping_timeout)
        conn.request("GET", spec.health_path)
        resp = conn.getresponse()
        code = resp.status
        conn.close()
        expected_start, expected_end = spec.health_expected_status
        return expected_start <= code <= expected_end
    except Exception:
        return False
