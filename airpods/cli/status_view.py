"""Status view rendering for pod health, ports, and service availability.

This module handles the display logic for the `status` command, including:
- Rendering Rich tables with pod information
- HTTP health checks for running services
- Port binding resolution and URL formatting
"""

from __future__ import annotations

import http.client
import socket
import time
from typing import Any, List, Optional

from airpods import ui
from airpods.logging import console
from airpods.services import ServiceSpec

from .common import DEFAULT_PING_TIMEOUT, manager


def render_status(specs: List[ServiceSpec]) -> None:
    """Render the pod status table.

    Args:
        specs: List of service specifications to check status for.

    Note:
        manager.pod_status_rows() returns a dict mapping pod names to status info,
        or an empty dict if no pods are running.
    """
    pod_rows = manager.pod_status_rows()
    if pod_rows is None:
        pod_rows = {}
    table = ui.themed_table(title="[accent]Pods[/accent]")
    table.add_column("Service")
    table.add_column("Status")
    table.add_column("Info", no_wrap=False)

    for spec in specs:
        row = pod_rows.get(spec.pod) if pod_rows else None
        if not row:
            table.add_row(spec.name, "[warn]absent", "-")
            continue

        status = row.get("Status", "?")

        if status == "Running":
            port_bindings = manager.service_ports(spec)
            host_ports = collect_host_ports(spec, port_bindings)
            host_port = host_ports[0] if host_ports else None
            health = ping_service(spec, host_port)
            url_text = ", ".join(format_host_urls(host_ports)) if host_ports else "-"
            table.add_row(spec.name, health, url_text)
        elif status == "Exited":
            port_bindings = manager.service_ports(spec)
            ports_display = format_port_bindings(port_bindings)
            table.add_row(spec.name, f"[warn]{status}", ports_display)
        else:
            table.add_row(spec.name, f"[warn]{status}", "-")

    console.print(table)


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
    """Format user-friendly localhost URLs for each host port."""
    return [f"http://localhost:{port}" for port in host_ports]


def format_port_bindings(port_bindings: dict[str, Any]) -> str:
    """Format port bindings for display."""
    ports: list[str] = []
    for container_port, bindings in port_bindings.items():
        for binding in bindings or []:
            host_port = binding.get("HostPort", "")
            if host_port:
                ports.append(f"{host_port}->{container_port}")
    return ", ".join(ports) if ports else "-"


def ping_service(spec: ServiceSpec, port: Optional[int]) -> str:
    """Ping a service's health endpoint and return status.

    Args:
        spec: Service specification containing health_path
        port: Host port to connect to

    Returns:
        Formatted status string with HTTP code and latency, or error type
    """
    if not spec.health_path or port is None:
        return "-"
    try:
        start = time.perf_counter()
        conn = http.client.HTTPConnection(
            "127.0.0.1", port, timeout=DEFAULT_PING_TIMEOUT
        )
        conn.request("GET", spec.health_path)
        resp = conn.getresponse()
        code = resp.status
        conn.close()
        elapsed_ms = (time.perf_counter() - start) * 1000
        if 200 <= code < 400:
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


def check_service_health(spec: ServiceSpec, port: Optional[int]) -> bool:
    """Check if a service is healthy (returns True/False).

    Args:
        spec: Service specification containing health_path
        port: Host port to connect to

    Returns:
        True if service is healthy (2xx-3xx response), False otherwise
    """
    if not spec.health_path or port is None:
        return False
    try:
        conn = http.client.HTTPConnection(
            "127.0.0.1", port, timeout=DEFAULT_PING_TIMEOUT
        )
        conn.request("GET", spec.health_path)
        resp = conn.getresponse()
        code = resp.status
        conn.close()
        return 200 <= code < 400
    except Exception:
        return False
