"""Start command implementation for launching Podman containers."""

from __future__ import annotations

import time
from typing import Optional

import typer
from rich.live import Live
from rich.spinner import Spinner
from rich.table import Table

from airpods import state, ui
from airpods.logging import console, status_spinner
from airpods.system import detect_gpu
from airpods.services import ServiceSpec

from ..common import (
    COMMAND_CONTEXT,
    DEFAULT_STARTUP_TIMEOUT,
    DEFAULT_STARTUP_CHECK_INTERVAL,
    ensure_podman_available,
    format_transfer_label,
    manager,
    print_network_status,
    print_volume_status,
    refresh_cli_context,
    resolve_services,
)
from ..completions import service_name_completion
from ..help import command_help_option, maybe_show_command_help
from ..status_view import check_service_health, collect_host_ports
from ..type_defs import CommandMap


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
        init_only: bool = typer.Option(
            False,
            "--init",
            "-i",
            help="Only run dependency checks, resource creation, and image pulls without starting services.",
        ),
    ) -> None:
        """Start pods for specified services."""
        maybe_show_command_help(ctx, help_)

        # Ensure user config exists
        from airpods.configuration import locate_config_file
        from airpods.state import configs_dir
        from airpods.configuration.defaults import DEFAULT_CONFIG_DICT
        import tomlkit
        from airpods.paths import detect_repo_root

        user_config_path = configs_dir() / "config.toml"
        repo_root = detect_repo_root()

        config_path = locate_config_file()
        if not user_config_path.exists():
            should_create = config_path is None
            if not should_create and repo_root and config_path:
                should_create = config_path.is_relative_to(repo_root)
            if should_create:
                user_config_path.parent.mkdir(parents=True, exist_ok=True)
                document = tomlkit.document()
                document.update(DEFAULT_CONFIG_DICT)
                user_config_path.write_text(tomlkit.dumps(document), encoding="utf-8")
                console.print(f"[ok]Created default config at {user_config_path}[/]")
                refresh_cli_context()
                config_path = user_config_path

        if config_path is None:
            config_path = locate_config_file()
        if config_path:
            console.print(f"[info]Config file: {config_path}")
        else:
            console.print("[warn]No config file found; using built-in defaults.[/]")

        specs = resolve_services(service)
        ensure_podman_available()

        if init_only:
            _run_init_mode(specs)
            return

        if not specs:
            console.print(
                "[warn]No services are enabled for this configuration; nothing to start.[/]"
            )
            return

        # Check what's already running first
        pod_rows = manager.pod_status_rows() or {}
        already_running = []
        needs_start = []

        for spec in specs:
            row = pod_rows.get(spec.pod)
            if row and row.get("Status") == "Running":
                # Verify the container is actually running
                if manager.container_exists(spec):
                    already_running.append(spec)
                else:
                    needs_start.append(spec)
            else:
                needs_start.append(spec)

        # If everything is already running, just report and exit
        if not needs_start:
            console.print("[ok]All services already running[/]")
            from airpods.cli.status_view import render_status

            render_status(specs)
            return

        # Report what's already running
        if already_running:
            running_names = ", ".join(spec.name for spec in already_running)
            console.print(f"Already running: [ok]{running_names}[/]")

        # Only process services that need to be started
        specs_to_start = needs_start

        # Show GPU status
        gpu_available, gpu_detail = detect_gpu()
        if gpu_available:
            console.print(f"GPU: [ok]enabled[/] ({gpu_detail})")
        else:
            console.print(f"GPU: [muted]not detected[/] ({gpu_detail})")

        # Only ensure network/volumes if we're actually starting something
        with status_spinner("Ensuring network"):
            network_created = manager.ensure_network()
        print_network_status(network_created, manager.network_name)

        with status_spinner("Ensuring volumes"):
            volume_results = manager.ensure_volumes(specs_to_start)
        print_volume_status(volume_results)

        # Sync Open WebUI plugins if webui is being started
        from airpods import plugins

        webui_specs = [s for s in specs_to_start if s.name == "open-webui"]
        if webui_specs:
            with status_spinner("Syncing Open WebUI plugins"):
                synced = plugins.sync_plugins()
            if synced > 0:
                console.print(f"[ok]✓[/] Synced {synced} plugin(s)")
            else:
                console.print("[info]Plugins already up-to-date[/]")

        # Initialize service states for the unified table
        service_states: dict[str, str] = {
            spec.name: "pulling" for spec in specs_to_start
        }
        service_urls: dict[str, str] = {spec.name: "" for spec in specs_to_start}
        service_transfers: dict[str, str] = {}
        pull_start_times: dict[str, float] = {}
        start_time = time.time()

        def _make_unified_table() -> Table:
            """Create the unified startup table showing all phases."""
            table = ui.themed_table(
                title="[info]Starting Services",
            )
            table.add_column("Service", style="cyan")
            table.add_column("Image", style="dim")
            table.add_column("Transfer", style="dim", justify="right")
            table.add_column("Status", style="")

            for spec in specs_to_start:
                state_val = service_states[spec.name]
                url = service_urls[spec.name]
                transfer = service_transfers.get(spec.name, "")

                if state_val == "pulling":
                    spinner = Spinner("dots", style="info")
                    table.add_row(spec.name, spec.image, transfer, spinner)
                elif state_val == "pulled":
                    table.add_row(spec.name, spec.image, transfer, "[ok]✓ Ready")
                elif state_val == "starting":
                    spinner = Spinner("dots", style="info")
                    table.add_row(spec.name, spec.image, transfer, spinner)
                elif state_val == "started":
                    spinner = Spinner("dots", style="info")
                    table.add_row(spec.name, spec.image, transfer, spinner)
                elif state_val == "healthy":
                    if url:
                        table.add_row(spec.name, spec.image, transfer, f"[ok]✓ {url}")
                    else:
                        table.add_row(spec.name, spec.image, transfer, "[ok]✓ Healthy")
                elif state_val == "failed":
                    table.add_row(spec.name, spec.image, transfer, "[error]✗ Failed")
                elif state_val == "timeout":
                    table.add_row(spec.name, spec.image, transfer, "[warn]⏱ Timeout")

            elapsed = time.time() - start_time
            table.caption = f"[dim]Elapsed: {int(elapsed)}s"
            return table

        with Live(_make_unified_table(), refresh_per_second=4, console=console) as live:
            # Pull images
            def _image_progress(phase, index, _total_count, spec):
                if phase == "start":
                    service_states[spec.name] = "pulling"
                    pull_start_times[spec.name] = time.perf_counter()
                    service_transfers[spec.name] = "[dim]estimating..."
                else:
                    service_states[spec.name] = "pulled"
                    elapsed = time.perf_counter() - pull_start_times.pop(
                        spec.name, time.perf_counter()
                    )
                    size = manager.runtime.image_size(spec.image)
                    transfer = format_transfer_label(size, elapsed)
                    service_transfers[spec.name] = transfer or f"{elapsed:.1f}s"
                live.update(_make_unified_table())

            manager.pull_images(specs_to_start, progress_callback=_image_progress)
            live.update(_make_unified_table())

            # Start containers
            for spec in specs_to_start:
                service_states[spec.name] = "starting"
                live.update(_make_unified_table())
                result = manager.start_service(
                    spec, gpu_available=gpu_available, force_cpu=force_cpu
                )
                # Don't log status here - it breaks Live rendering
                # Status is visible in the table already
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
                for spec in specs_to_start:
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
            spec.name
            for spec in specs_to_start
            if service_states.get(spec.name) == "failed"
        ]
        timeout_services = [
            spec.name
            for spec in specs_to_start
            if service_states.get(spec.name) == "timeout"
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

    return {"start": start}


def _run_init_mode(specs: list[ServiceSpec]) -> None:
    report = manager.report_environment()
    ui.show_environment(report)

    if report.missing:
        console.print(
            f"[error]The following dependencies are required: {', '.join(report.missing)}. Install them and re-run with --init.[/]"
        )
        raise typer.Exit(code=1)

    with status_spinner("Ensuring network"):
        network_created = manager.ensure_network()
    print_network_status(network_created, manager.network_name)

    with status_spinner("Ensuring volumes"):
        volume_results = manager.ensure_volumes(specs)
    print_volume_status(volume_results)

    _pull_images_only(specs)

    with status_spinner("Preparing Open WebUI secret"):
        state.ensure_webui_secret()
    console.print(f"[info]Open WebUI secret stored at {state.webui_secret_path()}[/]")

    ui.success_panel("init complete. pods are ready to start.")


def _pull_images_only(specs: list[ServiceSpec]) -> None:
    if not specs:
        console.print("[warn]No services enabled; nothing to initialize.[/]")
        return

    image_states: dict[str, str] = {spec.name: "pending" for spec in specs}
    image_transfers: dict[str, str] = {}
    image_start_times: dict[str, float] = {}

    def _make_table() -> Table:
        table = ui.themed_table(title="[info]Pulling Images")
        table.add_column("Service", style="cyan")
        table.add_column("Image", style="dim")
        table.add_column("Transfer", style="dim", justify="right")
        table.add_column("Status", style="")

        for spec in specs:
            state_val = image_states[spec.name]
            transfer = image_transfers.get(spec.name, "")
            if state_val == "pending":
                table.add_row(spec.name, spec.image, transfer, "[dim]Waiting...")
            elif state_val == "pulling":
                spinner = Spinner("dots", style="info")
                table.add_row(spec.name, spec.image, transfer, spinner)
            elif state_val == "done":
                table.add_row(spec.name, spec.image, transfer, "[ok]✓ Ready")

        return table

    with Live(_make_table(), refresh_per_second=4, console=console) as live:

        def _image_progress(phase, index, _total_count, spec):
            if phase == "start":
                image_states[spec.name] = "pulling"
                image_start_times[spec.name] = time.perf_counter()
                image_transfers[spec.name] = "[dim]estimating..."
            else:
                image_states[spec.name] = "done"
                elapsed = time.perf_counter() - image_start_times.pop(
                    spec.name, time.perf_counter()
                )
                size = manager.runtime.image_size(spec.image)
                transfer = format_transfer_label(size, elapsed)
                image_transfers[spec.name] = transfer or f"{elapsed:.1f}s"
            live.update(_make_table())

        manager.pull_images(specs, progress_callback=_image_progress)
        live.update(_make_table())
