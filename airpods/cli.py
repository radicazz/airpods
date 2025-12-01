from __future__ import annotations

import sys
import http.client
from typing import List, Optional

import click
import typer
from rich.table import Table

from airpods import __version__
from airpods import podman, state, ui
from airpods.config import REGISTRY
from airpods.logging import console, status_spinner
from airpods.services import ServiceManager, ServiceSpec, UnknownServiceError
from airpods.system import check_dependency, detect_gpu

HELP_OPTION_NAMES = ["-h", "--help"]
COMMAND_CONTEXT = {"help_option_names": HELP_OPTION_NAMES}

app = typer.Typer(
    help="Orchestrate local AI services (Ollama, Open WebUI) with Podman + UV.",
    context_settings={"help_option_names": []},
    rich_markup_mode="rich",
)

manager = ServiceManager(REGISTRY)

COMMAND_ALIASES = {
    "up": "start",
    "down": "stop",
    "ps": "status",
}
COMMAND_ALIAS_GROUPS: dict[str, List[str]] = {}
for alias, canonical in COMMAND_ALIASES.items():
    COMMAND_ALIAS_GROUPS.setdefault(canonical, []).append(alias)
for alias_list in COMMAND_ALIAS_GROUPS.values():
    alias_list.sort()

HELP_EXAMPLES = [
    ("airpods init", "Verify dependencies, volumes, and secrets before first run."),
    ("airpods start", "Launch Ollama and Open WebUI with GPU auto-detect."),
    ("airpods start --cpu open-webui", "Force CPU mode when starting only Open WebUI."),
    ("airpods status", "Show pod health, ports, and ping results."),
    ("airpods logs ollama -n 100", "Tail the latest Ollama logs."),
]


def _show_root_help(ctx: typer.Context) -> None:
    console.print(f"[bold]airpods[/bold] v{__version__}")
    console.print("Orchestrate local AI services (Ollama, Open WebUI) with Podman + UV.")
    console.print()
    console.print("[bold cyan]Usage[/bold cyan]")
    console.print("  airpods [OPTIONS] COMMAND [ARGS]...\n")
    console.print("[bold cyan]Commands[/bold cyan]")
    console.print(_build_command_table(ctx))
    console.print()
    console.print("[bold cyan]Options[/bold cyan]")
    console.print(_build_option_table(ctx))
    console.print()
    console.print("[bold cyan]Examples[/bold cyan]")
    console.print(_build_examples_table())


def _build_command_table(ctx: typer.Context) -> Table:
    table = Table.grid(padding=(0, 3))
    table.add_column(style="cyan", no_wrap=True)
    table.add_column(style="magenta", no_wrap=True)
    table.add_column()
    for row in _command_help_rows(ctx):
        table.add_row(*row)
    return table


def _build_option_table(ctx: typer.Context) -> Table:
    table = Table.grid(padding=(0, 3))
    table.add_column(style="cyan", no_wrap=True)
    table.add_column(style="magenta", no_wrap=True)
    table.add_column()
    for row in _option_help_rows(ctx):
        table.add_row(*row)
    return table


def _command_help_rows(ctx: typer.Context):
    command_group = ctx.command
    for name in command_group.list_commands(ctx):
        command = command_group.get_command(ctx, name)
        if not command or command.hidden:
            continue
        alias_text = ", ".join(COMMAND_ALIAS_GROUPS.get(name, []))
        description = (command.help or command.short_help or "").strip()
        yield (name, alias_text, description)


def _option_help_rows(ctx: typer.Context):
    for param in ctx.command.params:
        if not isinstance(param, click.Option):
            continue
        name = _primary_long_option(param)
        short_text = _format_short_options(param)
        description = (param.help or "").strip()
        yield (name, short_text, description)


def _primary_long_option(param: click.Option) -> str:
    for opt in param.opts:
        if opt.startswith("--"):
            return opt
    return param.opts[0] if param.opts else ""


def _format_short_options(param: click.Option) -> str:
    seen: List[str] = []
    for opt in list(param.opts) + list(param.secondary_opts):
        if not opt.startswith("-") or opt.startswith("--"):
            continue
        if opt not in seen:
            seen.append(opt)
    return ", ".join(seen)


def _build_examples_table() -> Table:
    table = Table.grid(padding=(0, 3))
    table.add_column(style="cyan", no_wrap=True)
    table.add_column()
    for command, description in HELP_EXAMPLES:
        table.add_row(f"[bold]{command}[/]", description)
    return table


def _print_version() -> None:
    console.print(f"airpods {__version__}")


@app.callback(invoke_without_command=True)
def _root_command(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "-v",
        "--version",
        help="Show CLI version and exit.",
        is_eager=True,
    ),
    help_: bool = typer.Option(
        False,
        "--help",
        "-h",
        help="Show this message and exit.",
        is_eager=True,
    ),
) -> None:
    if version:
        _print_version()
        raise typer.Exit()
    if help_:
        _show_root_help(ctx)
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        _show_root_help(ctx)


def _resolve_services(names: Optional[List[str]]) -> List[ServiceSpec]:
    try:
        return manager.resolve(names)
    except UnknownServiceError as exc:  # noqa: B904
        raise typer.BadParameter(str(exc))


def _ensure_podman_available() -> None:
    try:
        manager.ensure_podman()
    except podman.PodmanError as exc:
        console.print(f"[error]{exc}[/]")
        raise typer.Exit(code=1)


@app.command(context_settings=COMMAND_CONTEXT)
def version() -> None:
    """Show CLI version."""
    _print_version()


@app.command(context_settings=COMMAND_CONTEXT)
def init() -> None:
    """Verify tools, create volumes, and pre-pull images."""
    report = manager.report_environment()
    ui.show_environment(report)

    if report.missing:
        console.print(
            f"[error]The following dependencies are required: {', '.join(report.missing)}. Install them and re-run init.[/]"
        )
        raise typer.Exit(code=1)

    with status_spinner("Ensuring network"):
        manager.ensure_network()

    with status_spinner("Ensuring volumes"):
        manager.ensure_volumes(manager.resolve(None))

    with status_spinner("Pulling images"):
        manager.pull_images(manager.resolve(None))

    # Security: ensure a persistent secret key for Open WebUI sessions.
    with status_spinner("Preparing Open WebUI secret"):
        secret = state.ensure_webui_secret()
    console.print(f"[info]Open WebUI secret stored at {state.webui_secret_path()}[/]")

    ui.success_panel("init complete. pods are ready to start.")


@app.command(context_settings=COMMAND_CONTEXT)
def start(
    service: Optional[List[str]] = typer.Argument(None, help="Services to start (default: all)."),
    force_cpu: bool = typer.Option(False, "--cpu", help="Force CPU even if GPU is present."),
) -> None:
    """Start pods for specified services (default: ollama + open-webui)."""
    specs = _resolve_services(service)
    _ensure_podman_available()
    gpu_available, gpu_detail = detect_gpu()
    console.print(f"[info]GPU: {'enabled' if gpu_available else 'not detected'} ({gpu_detail})[/]")

    with status_spinner("Ensuring network"):
        manager.ensure_network()

    with status_spinner("Ensuring volumes"):
        manager.ensure_volumes(specs)

    with status_spinner("Pulling images"):
        manager.pull_images(specs)

    for spec in specs:
        with status_spinner(f"Starting {spec.name}"):
            manager.start_service(spec, gpu_available=gpu_available, force_cpu=force_cpu)
        console.print(f"[ok]{spec.name} running in pod {spec.pod}[/]")
    ui.success_panel(f"start complete: {', '.join(spec.name for spec in specs)}")


app.command(name="up", help="[alias]Alias for start[/]", hidden=True, context_settings=COMMAND_CONTEXT)(start)


@app.command(context_settings=COMMAND_CONTEXT)
def stop(
    service: Optional[List[str]] = typer.Argument(None, help="Services to stop (default: all)."),
    remove: bool = typer.Option(False, "--remove", "-r", help="Remove pods after stopping."),
    timeout: int = typer.Option(10, "--timeout", "-t", help="Stop timeout seconds."),
) -> None:
    """Stop pods for specified services."""
    specs = _resolve_services(service)
    _ensure_podman_available()
    for spec in specs:
        with status_spinner(f"Stopping {spec.pod}"):
            existed = manager.stop_service(spec, remove=remove, timeout=timeout)
        if not existed:
            console.print(f"[warn]{spec.pod} not found; skipping[/]")
            continue
        console.print(f"[ok]{spec.name} stopped[/]")
    ui.success_panel(f"stop complete: {', '.join(spec.name for spec in specs)}")


app.command(name="down", help="[alias]Alias for stop[/]", hidden=True, context_settings=COMMAND_CONTEXT)(stop)


@app.command(context_settings=COMMAND_CONTEXT)
def status(service: Optional[List[str]] = typer.Argument(None, help="Services to report (default: all).")) -> None:
    """Show pod status."""
    specs = _resolve_services(service)
    _ensure_podman_available()
    pod_rows = manager.pod_status_rows()

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
        port_bindings = manager.service_ports(spec)
        ports = []
        for container_port, bindings in port_bindings.items():
            for binding in bindings or []:
                host_port = binding.get("HostPort", "")
                ports.append(f"{host_port}->{container_port}")
        ports_display = ", ".join(ports) if ports else (", ".join(row.get("Ports", [])) if row.get("Ports") else "-")
        containers = str(row.get("NumberOfContainers", "?") or "?")
        host_port = _extract_host_port(spec, port_bindings)
        ping_status = _ping_service(spec, host_port) if host_port else "-"
        table.add_row(spec.name, spec.pod, row.get("Status", "?"), ports_display, containers, ping_status)

    console.print(table)


app.command(name="ps", help="[alias]Alias for status[/]", hidden=True, context_settings=COMMAND_CONTEXT)(status)


@app.command(context_settings=COMMAND_CONTEXT)
def alias() -> None:
    """Show command aliases."""
    ui.show_command_aliases(COMMAND_ALIASES)


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


@app.command(context_settings=COMMAND_CONTEXT)
def logs(
    service: Optional[List[str]] = typer.Argument(None, help="Services to show logs for (default: all)."),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow logs."),
    since: Optional[str] = typer.Option(None, "--since", help="Show logs since RFC3339 timestamp or duration."),
    lines: int = typer.Option(200, "--lines", "-n", help="Number of log lines to show."),
) -> None:
    """Show pod logs."""
    specs = _resolve_services(service)
    _ensure_podman_available()
    if follow and len(specs) > 1:
        console.print("[warn]follow with multiple services will stream sequentially; Ctrl+C to stop.[/]")

    for idx, spec in enumerate(specs):
        if idx > 0:
            console.print()
        ui.info_panel(f"Logs for {spec.name} ({spec.container})")
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
