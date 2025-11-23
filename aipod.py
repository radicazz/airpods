from __future__ import annotations

import sys
import http.client
from typing import List, Optional

import typer
from rich.panel import Panel
from rich.table import Table

from aipod import __version__
from aipod import podman
from aipod.config import SERVICES, ServiceSpec, get_service, list_service_names
from aipod.logging import console, status_spinner
from aipod import state
from aipod.system import CheckResult, check_dependency, detect_gpu

app = typer.Typer(
    help="Orchestrate local AI services (Ollama, Open WebUI) with Podman + UV.",
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _resolve_services(names: Optional[List[str]]) -> List[ServiceSpec]:
    if not names:
        return list(SERVICES.values())
    resolved: List[ServiceSpec] = []
    for name in names:
        spec = get_service(name)
        if not spec:
            raise typer.BadParameter(f"unknown service '{name}'. available: {', '.join(list_service_names())}")
        resolved.append(spec)
    return resolved


def _print_checks(checks: List[CheckResult], gpu_available: bool, gpu_detail: str) -> None:
    table = Table(title="Environment", show_header=True, header_style="bold cyan")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Details")
    for check in checks:
        status = "[ok]ok" if check.ok else "[error]missing"
        table.add_row(check.name, status, check.detail)
    table.add_row("gpu (nvidia)", "[ok]ok" if gpu_available else "[warn]not detected", gpu_detail)
    console.print(table)


def _ensure_podman_available() -> None:
    check = check_dependency("podman", ["--version"])
    if not check.ok:
        console.print("[error]podman is required; install it and re-run.[/]")
        raise typer.Exit(code=1)


@app.command()
def version() -> None:
    """Show CLI version."""
    console.print(f"aipod {__version__}")


@app.command()
def init() -> None:
    """Verify tools, create volumes, and pre-pull images."""
    checks = [
        check_dependency("podman", ["--version"]),
        check_dependency("podman-compose", ["--version"]),
        check_dependency("uv", ["--version"]),
    ]
    gpu_available, gpu_detail = detect_gpu()
    _print_checks(checks, gpu_available, gpu_detail)

    if not checks[0].ok:
        console.print("[error]podman is required; install it and re-run init.[/]")
        raise typer.Exit(code=1)

    with status_spinner("Ensuring volumes"):
        for spec in SERVICES.values():
            for volume, _ in spec.volumes:
                podman.ensure_volume(volume)

    with status_spinner("Pulling images"):
        for spec in SERVICES.values():
            podman.pull_image(spec.image)

    # Security: ensure a persistent secret key for Open WebUI sessions.
    with status_spinner("Preparing Open WebUI secret"):
        secret = state.ensure_webui_secret()
    console.print(f"[info]Open WebUI secret stored at {state.config_dir() / 'webui_secret'}[/]")

    console.print(Panel.fit("[ok]init complete. pods are ready to start.[/]", border_style="green"))


@app.command()
def start(
    service: Optional[List[str]] = typer.Argument(None, help="Services to start (default: all)."),
    force_cpu: bool = typer.Option(False, "--cpu", help="Force CPU even if GPU is present."),
) -> None:
    """Start pods for specified services (default: ollama + open-webui)."""
    specs = _resolve_services(service)
    _ensure_podman_available()
    gpu_available, gpu_detail = detect_gpu()
    console.print(f"[info]GPU: {'enabled' if gpu_available else 'not detected'} ({gpu_detail})[/]")

    with status_spinner("Ensuring volumes"):
        for spec in specs:
            for volume, _ in spec.volumes:
                podman.ensure_volume(volume)

    with status_spinner("Pulling images"):
        for spec in specs:
            podman.pull_image(spec.image)

    for spec in specs:
        with status_spinner(f"Creating pod {spec.pod}"):
            podman.ensure_pod(spec.pod, spec.ports)
        with status_spinner(f"Starting {spec.name}"):
            use_gpu = spec.needs_gpu and gpu_available and not force_cpu
            env = dict(spec.env)
            if spec.name == "open-webui":
                env["WEBUI_SECRET_KEY"] = state.ensure_webui_secret()
            podman.run_container(
                pod=spec.pod,
                name=spec.container,
                image=spec.image,
                env=env,
                volumes=spec.volumes,
                gpu=use_gpu,
            )
        console.print(f"[ok]{spec.name} running in pod {spec.pod}[/]")


@app.command()
def stop(
    service: Optional[List[str]] = typer.Argument(None, help="Services to stop (default: all)."),
    remove: bool = typer.Option(False, "--remove", "-r", help="Remove pods after stopping."),
    timeout: int = typer.Option(10, "--timeout", "-t", help="Stop timeout seconds."),
) -> None:
    """Stop pods for specified services."""
    specs = _resolve_services(service)
    for spec in specs:
        if not podman.pod_exists(spec.pod):
            console.print(f"[warn]{spec.pod} not found; skipping[/]")
            continue
        with status_spinner(f"Stopping {spec.pod}"):
            podman.stop_pod(spec.pod, timeout=timeout)
        if remove:
            with status_spinner(f"Removing {spec.pod}"):
                podman.remove_pod(spec.pod)
        console.print(f"[ok]{spec.name} stopped[/]")


@app.command()
def status(service: Optional[List[str]] = typer.Argument(None, help="Services to report (default: all).")) -> None:
    """Show pod status."""
    specs = _resolve_services(service)
    pod_rows = {row.get("Name"): row for row in podman.pod_status()}

    table = Table(title="Pods", header_style="bold cyan")
    table.add_column("Service")
    table.add_column("Pod")
    table.add_column("Status")
    table.add_column("Ports")
    table.add_column("Containers")
    table.add_column("Ping")

    for spec in specs:
        row = pod_rows.get(spec.pod)
        if not row:
            table.add_row(spec.name, spec.pod, "[warn]absent", "-", "-", "-")
            continue
        inspect_info = podman.pod_inspect(spec.pod) or {}
        port_bindings = inspect_info.get("InfraConfig", {}).get("PortBindings", {}) if inspect_info else {}
        ports = []
        for container_port, bindings in port_bindings.items():
            for binding in bindings or []:
                host_port = binding.get("HostPort", "")
                ports.append(f"{host_port}->{container_port}")
        ports_display = ", ".join(ports) if ports else (", ".join(row.get("Ports", [])) if row.get("Ports") else "-")
        containers = str(len(inspect_info.get("Containers", []))) if inspect_info else str(row.get("NumberOfContainers", "?") or "?")
        host_port = _extract_host_port(spec, port_bindings)
        ping_status = _ping_service(spec, host_port) if host_port else "-"
        table.add_row(spec.name, spec.pod, row.get("Status", "?"), ports_display, containers, ping_status)

    console.print(table)


def _extract_host_port(spec: ServiceSpec, port_bindings) -> Optional[int]:
    # Prefer actual bindings; fallback to configured host port.
    if port_bindings:
        first_binding = next(iter(port_bindings.values()), None)
        if first_binding:
            host_port = (first_binding[0] or {}).get("HostPort")
            if host_port:
                try:
                    return int(host_port)
                except ValueError:
                    return None
    if spec.ports:
        return spec.ports[0][0]
    return None


def _ping_service(spec: ServiceSpec, port: Optional[int]) -> str:
    if not spec.health_path or port is None:
        return "-"
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2.0)
        conn.request("GET", spec.health_path)
        resp = conn.getresponse()
        code = resp.status
        conn.close()
        if 200 <= code < 400:
            return "[ok]ok"
        return f"[warn]{code}"
    except Exception as exc:  # noqa: BLE001
        return f"[warn]{type(exc).__name__}"


@app.command()
def logs(
    service: Optional[List[str]] = typer.Argument(None, help="Services to show logs for (default: all)."),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow logs."),
    since: Optional[str] = typer.Option(None, "--since", help="Show logs since RFC3339 timestamp or duration."),
    lines: int = typer.Option(200, "--lines", "-n", help="Number of log lines to show."),
) -> None:
    """Show pod logs."""
    specs = _resolve_services(service)
    if follow and len(specs) > 1:
        console.print("[warn]follow with multiple services will stream sequentially; Ctrl+C to stop.[/]")

    for idx, spec in enumerate(specs):
        if idx > 0:
            console.print()
        console.print(Panel.fit(f"[info]Logs for {spec.name} ({spec.container})[/]", border_style="cyan"))
        code = podman.stream_logs(spec.container, follow=follow, tail=lines, since=since)
        if code != 0:
            console.print(f"[warn]podman logs exited with code {code} for {spec.container}[/]")


def main() -> None:
    try:
        app()
    except podman.PodmanError as exc:
        console.print(f"[error]{exc}[/]")
        sys.exit(1)


if __name__ == "__main__":
    main()
