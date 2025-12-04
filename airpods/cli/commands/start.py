"""Start command implementation for launching Podman containers."""

from __future__ import annotations

import time
from typing import Optional

import typer
from rich.live import Live
from rich.spinner import Spinner
from rich.table import Table

from airpods import ui
from airpods.logging import console, status_spinner
from airpods.system import detect_gpu
from airpods.services import ServiceStartResult

from ..common import (
    COMMAND_CONTEXT,
    DEFAULT_STARTUP_TIMEOUT,
    DEFAULT_STARTUP_CHECK_INTERVAL,
    ensure_podman_available,
    manager,
    print_network_status,
    print_volume_status,
    resolve_services,
)
from ..completions import service_name_completion
from ..help import command_help_option, maybe_show_command_help
from ..status_view import check_service_health, collect_host_ports
from ..type_defs import CommandMap


def _log_service_start_status(result: ServiceStartResult) -> None:
    """Emit human-friendly status for pod/container reuse."""

    if result.pod_created:
        console.print(f"[ok]Created pod {result.spec.pod}")
    else:
        console.print(f"[info]Pod {result.spec.pod} already exists; reusing")

    if result.container_replaced:
        console.print(
            f"[info]Replaced existing container {result.spec.container} in pod {result.spec.pod}"
        )
    else:
        console.print(f"[ok]Started container {result.spec.container}")


def register(app: typer.Typer) -> CommandMap:
    @app.command(context_settings=COMMAND_CONTEXT)
    def start(
        ctx: typer.Context,
        help_: bool = command_help_option(),
        service: Optional[list[str]] = typer.Argument(
            None,
            help="Services to start (default: all).",
            shell_complete=service_name_completion,
        ),
        force_cpu: bool = typer.Option(
            False, "--cpu", help="Force CPU even if GPU is present."
        ),
        force: bool = typer.Option(
            False,
            "--force",
            "-f",
            help="Skip confirmation prompt before replacing existing containers.",
        ),
    ) -> None:
        """Start pods for specified services; prompts before replacing running containers."""
        maybe_show_command_help(ctx, help_)
        specs = resolve_services(service)
        ensure_podman_available()
        gpu_available, gpu_detail = detect_gpu()
        console.print(
            f"[info]GPU: {'enabled' if gpu_available else 'not detected'} ({gpu_detail})[/]"
        )

        with status_spinner("Ensuring network"):
            network_created = manager.ensure_network()
        print_network_status(network_created, manager.network_name)

        with status_spinner("Ensuring volumes"):
            volume_results = manager.ensure_volumes(specs)
        print_volume_status(volume_results)

        # Initialize service states for the unified table
        service_states: dict[str, str] = {spec.name: "pulling" for spec in specs}
        service_urls: dict[str, str] = {spec.name: "" for spec in specs}
        start_time = time.time()

        def _make_unified_table() -> Table:
            """Create the unified startup table showing all phases."""
            table = Table(
                title="[info]Starting Services",
                show_header=True,
                header_style="bold",
            )
            table.add_column("Service", style="cyan")
            table.add_column("Image", style="dim")
            table.add_column("Status", style="")

            for spec in specs:
                state_val = service_states[spec.name]
                url = service_urls[spec.name]

                if state_val == "pulling":
                    spinner = Spinner("dots", style="info")
                    table.add_row(spec.name, spec.image, spinner)
                elif state_val == "pulled":
                    table.add_row(spec.name, spec.image, "[ok]✓ Ready")
                elif state_val == "starting":
                    spinner = Spinner("dots", style="info")
                    table.add_row(spec.name, spec.image, spinner)
                elif state_val == "started":
                    spinner = Spinner("dots", style="info")
                    table.add_row(spec.name, spec.image, spinner)
                elif state_val == "healthy":
                    if url:
                        table.add_row(spec.name, spec.image, f"[ok]✓ {url}")
                    else:
                        table.add_row(spec.name, spec.image, "[ok]✓ Healthy")
                elif state_val == "failed":
                    table.add_row(spec.name, spec.image, "[error]✗ Failed")
                elif state_val == "timeout":
                    table.add_row(spec.name, spec.image, "[warn]⏱ Timeout")

            elapsed = time.time() - start_time
            table.caption = f"[dim]Elapsed: {int(elapsed)}s"
            return table

        with Live(_make_unified_table(), refresh_per_second=4, console=console) as live:
            # Pull images
            def _image_progress(phase, index, _total_count, spec):
                if phase == "start":
                    service_states[spec.name] = "pulling"
                else:
                    service_states[spec.name] = "pulled"
                live.update(_make_unified_table())

            manager.pull_images(specs, progress_callback=_image_progress)

            # Check for existing containers
            existing_containers = [
                spec for spec in specs if manager.container_exists(spec)
            ]
            if existing_containers and not force:
                live.stop()
                lines = "\n".join(
                    f"  - {spec.name} ({spec.container})"
                    for spec in existing_containers
                )
                prompt = f"Replace the following running containers before starting?\n{lines}"
                if not ui.confirm_action(prompt, default=False):
                    console.print("[warn]Start cancelled by user.[/]")
                    raise typer.Abort()
                live.start()

            # Start containers
            for spec in specs:
                service_states[spec.name] = "starting"
                live.update(_make_unified_table())
                result = manager.start_service(
                    spec, gpu_available=gpu_available, force_cpu=force_cpu
                )
                _log_service_start_status(result)
                service_states[spec.name] = "started"
                live.update(_make_unified_table())

            # Wait for health checks
            timeout_seconds = DEFAULT_STARTUP_TIMEOUT
            pending_states = {"starting", "started"}
            while True:
                elapsed = time.time() - start_time
                if elapsed >= timeout_seconds:
                    for name, state in service_states.items():
                        if state in pending_states:
                            service_states[name] = "timeout"
                    live.update(_make_unified_table())
                    break

                pod_rows = manager.pod_status_rows() or {}
                all_done = True
                for spec in specs:
                    state = service_states[spec.name]
                    if state in ("healthy", "failed", "timeout"):
                        continue
                    if state not in pending_states:
                        all_done = False
                        continue

                    row = pod_rows.get(spec.pod)
                    if not row:
                        all_done = False
                        continue

                    pod_status = (row.get("Status") or "").strip()

                    if pod_status in {"Exited", "Error"}:
                        service_states[spec.name] = "failed"
                        continue
                    if pod_status != "Running":
                        all_done = False
                        continue

                    port_bindings = manager.service_ports(spec)
                    host_ports = collect_host_ports(spec, port_bindings)
                    host_port = host_ports[0] if host_ports else None

                    if not spec.health_path or host_port is None:
                        service_states[spec.name] = "healthy"
                        if host_port:
                            service_urls[spec.name] = f"http://localhost:{host_port}"
                        continue

                    if check_service_health(spec, host_port):
                        service_states[spec.name] = "healthy"
                        service_urls[spec.name] = f"http://localhost:{host_port}"
                    else:
                        all_done = False

                live.update(_make_unified_table())

                if all_done:
                    break

                time.sleep(DEFAULT_STARTUP_CHECK_INTERVAL)

        failed = [
            spec.name for spec in specs if service_states.get(spec.name) == "failed"
        ]
        timeout_services = [
            spec.name for spec in specs if service_states.get(spec.name) == "timeout"
        ]

        if failed:
            console.print(
                f"\n[error]Failed services: {', '.join(failed)}. "
                "Check logs with 'airpods logs'[/]"
            )
            raise typer.Exit(code=1)

        if timeout_services:
            console.print(
                f"\n[warn]Timed out services: {', '.join(timeout_services)}. "
                "Services may still be starting. Check with 'airpods status'[/]"
            )

        if not failed and not timeout_services:
            ui.success_panel(
                f"start complete: {', '.join(spec.name for spec in specs)}"
            )

    return {"start": start}
