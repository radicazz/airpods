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
from airpods.system import detect_gpu, detect_cuda_compute_capability
from airpods.cuda import select_cuda_version, get_cuda_info_display
from airpods.services import ServiceSpec

from ..common import (
    COMMAND_CONTEXT,
    DEFAULT_STARTUP_TIMEOUT,
    DEFAULT_STARTUP_CHECK_INTERVAL,
    ensure_podman_available,
    format_transfer_label,
    is_verbose_mode,
    manager,
    print_network_status,
    print_volume_status,
    print_config_info,
    refresh_cli_context,
    resolve_services,
    get_cli_config,
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
        sequential: bool = typer.Option(
            False,
            "--sequential",
            help="Pull images sequentially (overrides cli.max_concurrent_pulls).",
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
        
        # Check verbose mode from context
        verbose = is_verbose_mode(ctx)
        print_config_info(config_path, verbose=verbose)

        specs = resolve_services(service)
        ensure_podman_available()

        # Enable CUDA logging during startup flows
        import airpods.config as config_module
        config_module.ENABLE_COMFY_CUDA_LOG = True

        cli_config = get_cli_config()
        max_concurrent_pulls = 1 if sequential else cli_config.max_concurrent_pulls

        if init_only:
            _run_init_mode(specs, max_concurrent_pulls)
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

        # Show CUDA detection info if ComfyUI is being started
        comfyui_specs = [s for s in specs_to_start if s.name == "comfyui"]
        if comfyui_specs:
            has_gpu_cap, gpu_name_cap, compute_cap = detect_cuda_compute_capability()
            if has_gpu_cap and compute_cap:
                selected_cuda = select_cuda_version(compute_cap)
                cuda_info = get_cuda_info_display(
                    has_gpu_cap, gpu_name_cap, compute_cap, selected_cuda
                )
                console.print(f"CUDA: [ok]{cuda_info}[/]")
            else:
                cuda_info = get_cuda_info_display(
                    has_gpu_cap, gpu_name_cap, compute_cap, "cu126"
                )
                console.print(f"CUDA: [muted]{cuda_info}[/]")

        # Only ensure network/volumes if we're actually starting something
        with status_spinner("Ensuring network"):
            network_created = manager.ensure_network()
        print_network_status(network_created, manager.network_name, verbose=verbose)

        with status_spinner("Ensuring volumes"):
            volume_results = manager.ensure_volumes(specs_to_start)
        print_volume_status(volume_results, verbose=verbose)

        # Sync Open WebUI plugins if webui is being started
        from airpods import plugins

        webui_specs = [s for s in specs_to_start if s.name == "open-webui"]
        if webui_specs:
            with status_spinner("Syncing Open WebUI plugins"):
                synced = plugins.sync_plugins()
            # Only show plugin sync messages if changes were made
            if synced > 0:
                console.print(f"[ok]Synced {synced} plugin(s)[/]")
            elif verbose:
                console.print("[info]Plugins already up-to-date[/]")

        # Simple log-based startup process
        service_urls: dict[str, str] = {}
        failed_services = []
        timeout_services = []
        
        # Pull images with simple logging
        def _image_progress(phase, index, _total_count, spec):
            if phase == "start":
                if verbose:
                    console.print(f"Pulling [accent]{spec.image}[/]...")
            else:
                if verbose:
                    elapsed = time.perf_counter() - pull_start_times.get(spec.name, 0)
                    size = manager.runtime.image_size(spec.image)
                    transfer = format_transfer_label(size, elapsed)
                    if transfer:
                        console.print(f"[ok]✓[/] Pulled {spec.name} ({transfer})")
                    else:
                        console.print(f"[ok]✓[/] Pulled {spec.name}")

        pull_start_times: dict[str, float] = {}
        def _track_pull_start(phase, index, _total_count, spec):
            if phase == "start":
                pull_start_times[spec.name] = time.perf_counter()
            _image_progress(phase, index, _total_count, spec)

        manager.pull_images(
            specs_to_start,
            progress_callback=_track_pull_start if verbose else lambda *args: None,
            max_concurrent=max_concurrent_pulls,
        )

        # Start services with simple logging
        for spec in specs_to_start:
            console.print(f"Starting [accent]{spec.name}[/]...")
            
            try:
                manager.start_service(
                    spec, gpu_available=gpu_available, force_cpu=force_cpu
                )
            except Exception as e:
                console.print(f"[error]✗ Failed to start {spec.name}: {e}[/]")
                failed_services.append(spec.name)
                continue

        # Wait for health checks with timeout
        start_time = time.time()
        timeout_seconds = DEFAULT_STARTUP_TIMEOUT
        
        while True:
            elapsed = time.time() - start_time
            if elapsed >= timeout_seconds:
                break
                
            pod_rows = manager.pod_status_rows() or {}
            all_done = True
            
            for spec in specs_to_start:
                if spec.name in failed_services:
                    continue
                    
                row = pod_rows.get(spec.pod)
                if not row:
                    all_done = False
                    continue
                    
                pod_status = (row.get("Status") or "").strip()
                
                if pod_status in {"Exited", "Error"}:
                    if spec.name not in failed_services:
                        failed_services.append(spec.name)
                    continue
                    
                if pod_status != "Running":
                    all_done = False
                    continue
                    
                # Service is running, check health if needed
                if spec.name in service_urls:
                    continue  # Already healthy
                    
                port_bindings = manager.service_ports(spec)
                host_ports = collect_host_ports(spec, port_bindings)
                host_port = host_ports[0] if host_ports else None
                
                if not spec.health_path or host_port is None:
                    # No health check needed
                    if host_port:
                        service_urls[spec.name] = f"http://localhost:{host_port}"
                    else:
                        service_urls[spec.name] = ""
                    continue
                    
                if check_service_health(spec, host_port):
                    service_urls[spec.name] = f"http://localhost:{host_port}"
                else:
                    all_done = False
                    
            if all_done:
                break
                
            time.sleep(DEFAULT_STARTUP_CHECK_INTERVAL)
            
        # Handle timeouts
        for spec in specs_to_start:
            if spec.name not in failed_services and spec.name not in service_urls:
                timeout_services.append(spec.name)

        # Categorize results  
        healthy_services = [name for name in service_urls.keys() if name not in failed_services]
        failed = failed_services

        # Show clean completion summary
        if healthy_services:
            urls = [
                service_urls.get(name)
                for name in healthy_services
                if service_urls.get(name)
            ]
            url_display = f" • {', '.join(urls)}" if urls else ""
            console.print(
                f"[ok]✓ Started {len(healthy_services)} service{'s' if len(healthy_services) != 1 else ''}{url_display}[/]"
            )

        if failed:
            console.print(
                f"[error]✗ Failed services: {', '.join(failed)}. "
                "Check logs with 'airpods logs'[/]"
            )
            raise typer.Exit(code=1)

        if timeout_services:
            console.print(
                f"[warn]⏱ Timed out services: {', '.join(timeout_services)}. "
                "Services may still be starting. Check with 'airpods status'[/]"
            )

        # Auto-import plugins into Open WebUI if service is healthy
        if webui_specs and "open-webui" in service_urls and "open-webui" not in failed_services:
            with status_spinner("Auto-importing plugins into Open WebUI"):
                try:
                    plugins_dir = plugins.get_plugins_target_dir()
                    container_name = webui_specs[0].container
                    imported = plugins.import_plugins_to_webui(
                        plugins_dir, container_name=container_name
                    )
                    if imported > 0:
                        console.print(
                            f"[ok]✓ Auto-imported {imported} plugin(s) into Open WebUI[/]"
                        )
                    elif verbose:
                        console.print(
                            "[info]No new plugins to import (may already exist)[/]"
                        )
                except Exception as e:
                    console.print(
                        f"[warn]Plugin auto-import failed: {e}. "
                        "Plugins are synced to filesystem and can be imported manually via UI.[/]"
                    )

    return {"start": start}


def _run_init_mode(specs: list[ServiceSpec], max_concurrent: int) -> None:
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

    _pull_images_only(specs, max_concurrent=max_concurrent)

    with status_spinner("Preparing Open WebUI secret"):
        state.ensure_webui_secret()
    console.print(f"[info]Open WebUI secret stored at {state.webui_secret_path()}[/]")

    ui.success_panel("init complete. pods are ready to start.")


def _pull_images_only(specs: list[ServiceSpec], max_concurrent: int) -> None:
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

    with Live(_make_table(), refresh_per_second=4, console=console, transient=True) as live:

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

        manager.pull_images(
            specs,
            progress_callback=_image_progress,
            max_concurrent=max_concurrent,
        )
        live.update(_make_table())
