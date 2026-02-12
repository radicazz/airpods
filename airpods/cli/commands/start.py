"""Start command implementation for launching Podman containers."""

from __future__ import annotations

import queue
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

import typer
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from airpods import ui
from airpods import __version__
from airpods.logging import console, status_spinner
from airpods.system import detect_gpu, detect_cuda_compute_capability
from airpods.cuda import select_cuda_version, get_cuda_info_display
from airpods.services import ServiceSpec
from airpods.configuration import get_config
from airpods import gguf, state

from ..common import (
    COMMAND_CONTEXT,
    ensure_runtime_available,
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

ensure_podman_available = ensure_runtime_available


def _webui_db_ready(container_name: str) -> bool:
    """Return True if the Open WebUI SQLite DB exists and has a function table."""
    code = r"""
import os
import sqlite3
import sys

DB_PATH = r"/app/backend/data/webui.db"
if not os.path.exists(DB_PATH):
    sys.exit(2)

try:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='function'"
    )
    ok = cur.fetchone() is not None
    conn.close()
    sys.exit(0 if ok else 3)
except Exception:
    sys.exit(4)
"""
    try:
        result = manager.runtime.exec_in_container(
            container_name,
            ["python3", "-c", code.strip()],
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
        )
    except Exception:
        return False
    return result.returncode == 0


def _maybe_sync_plugins(
    specs: list[ServiceSpec],
    *,
    verbose: bool,
    keep_custom_nodes: set[str] | None = None,
) -> tuple[int, int]:
    """Sync Open WebUI + ComfyUI plugins for requested services.

    Returns: (synced_webui, synced_comfyui)
    """
    from airpods import plugins

    synced_webui = 0
    synced_comfyui = 0

    if any(s.name == "open-webui" for s in specs):
        with status_spinner("Syncing Open WebUI plugins"):
            synced_webui = plugins.sync_plugins()
        if synced_webui > 0:
            console.print(f"[ok]Synced {synced_webui} plugin(s)[/]")
        elif verbose:
            console.print("[info]Plugins already up-to-date[/]")

    if any(s.name == "comfyui" for s in specs):
        with status_spinner("Syncing ComfyUI custom nodes"):
            synced_comfyui = plugins.sync_comfyui_plugins(keep=keep_custom_nodes)

        # Always show custom node status, even if nothing was synced
        total_nodes = plugins.count_comfyui_plugins()
        if synced_comfyui > 0:
            console.print(
                f"[ok]Synced {synced_comfyui} custom node(s) ({total_nodes} total active)[/]"
            )
        else:
            console.print(f"[ok]ComfyUI: {total_nodes} custom node(s) active[/]")

    return synced_webui, synced_comfyui


def _maybe_import_webui_plugins(
    specs: list[ServiceSpec],
    *,
    cli_config: "CLIConfig",
    verbose: bool,
) -> None:
    """Best-effort import of synced plugins into the Open WebUI DB.

    This runs even when services are already running and even when --wait is not used,
    so plugin updates land in Admin > Functions without requiring a container restart.
    """
    from airpods import plugins

    webui_specs = [s for s in specs if s.name == "open-webui"]
    if not webui_specs:
        return

    container_name = webui_specs[0].container
    plugins_dir = plugins.get_plugins_target_dir()

    # The DB may not be ready immediately after container start; retry briefly.
    timeout_seconds = min(cli_config.startup_timeout, 45)
    start_at = time.time()
    while time.time() - start_at < timeout_seconds:
        if _webui_db_ready(container_name):
            break
        time.sleep(max(0.5, float(cli_config.startup_check_interval)))

    if not _webui_db_ready(container_name):
        if verbose:
            console.print(
                "[warn]Open WebUI DB not ready; skipping plugin auto-import. "
                "Plugins are synced to filesystem and can be imported later.[/]"
            )
        return

    with status_spinner("Auto-importing plugins into Open WebUI"):
        try:
            owner_id = plugins.resolve_plugin_owner_user_id(
                manager.runtime, container_name, cli_config.plugin_owner
            )
            imported = plugins.import_plugins_to_webui(
                manager.runtime,
                plugins_dir,
                admin_user_id=owner_id,
                container_name=container_name,
            )
            if imported > 0:
                console.print(
                    f"[ok]✓ Auto-imported {imported} plugin(s) into Open WebUI[/]"
                )
            elif verbose:
                console.print("[info]No new plugins to import (may already exist)[/]")
        except Exception as e:
            console.print(
                f"[warn]Plugin auto-import failed: {e}. "
                "Plugins are synced to filesystem and can be imported manually via UI.[/]"
            )


def _comfyui_custom_nodes_container_dir(spec: ServiceSpec) -> str:
    for mount in spec.volumes:
        if mount.target.endswith("/custom_nodes"):
            return mount.target
    return "/root/ComfyUI/custom_nodes"


def _extract_flag_value(args: list[str], flag: str) -> str | None:
    for idx, arg in enumerate(args):
        if arg == flag and idx + 1 < len(args):
            return args[idx + 1]
    return None


def _map_container_path_to_host(spec: ServiceSpec, container_path: str) -> Path | None:
    for vol in spec.volumes:
        target = vol.target.rstrip("/")
        if container_path == target or container_path.startswith(f"{target}/"):
            rel = Path(container_path).relative_to(target)
            return Path(vol.source) / rel
    return None


def _ensure_comfyui_user_dirs(spec: ServiceSpec) -> None:
    user_dir = _extract_flag_value(spec.command or [], "--user-directory")
    if not user_dir:
        targets = {vol.target for vol in spec.volumes}
        if any(target.startswith("/basedir") for target in targets):
            user_dir = "/basedir/user"
        elif any(target.startswith("/workspace") for target in targets):
            user_dir = "/workspace/user"
        else:
            return

    host_user_dir = _map_container_path_to_host(spec, user_dir)
    if not host_user_dir:
        return

    # Precreate user/workflows paths so the container doesn't create them as root.
    (host_user_dir / "default" / "workflows").mkdir(parents=True, exist_ok=True)


def _maybe_prepare_custom_nodes(
    specs: list[ServiceSpec],
    *,
    nodes: list["CustomNodeInstall"],
    verbose: bool,
) -> tuple[list["CustomNodeInstall"], int]:
    from airpods import custom_nodes as custom_nodes_module

    comfyui_spec = next((spec for spec in specs if spec.name == "comfyui"), None)
    if not comfyui_spec:
        return [], 0

    if not nodes:
        return [], 0

    with status_spinner("Preparing ComfyUI custom nodes"):
        results = custom_nodes_module.prepare_custom_nodes(nodes, verbose=verbose)

    created = sum(1 for result in results if result.action in {"copied", "cloned"})
    errors = [result for result in results if result.action == "error"]
    skipped = sum(1 for result in results if result.action == "skipped")

    if created:
        console.print(f"[ok]Prepared {created} custom node(s)[/]")
    elif verbose:
        console.print("[info]Custom nodes already up-to-date[/]")

    if skipped and verbose:
        console.print(f"[info]Skipped {skipped} custom node(s)[/]")

    if errors:
        for result in errors:
            detail = f": {result.detail}" if result.detail else ""
            console.print(f"[warn]Custom node {result.name} failed{detail}[/]")

    return nodes, created


def _maybe_install_custom_node_requirements(
    specs: list[ServiceSpec],
    *,
    nodes: list["CustomNodeInstall"],
    verbose: bool,
) -> None:
    from airpods import custom_nodes as custom_nodes_module

    if not nodes:
        return

    comfyui_spec = next((spec for spec in specs if spec.name == "comfyui"), None)
    if not comfyui_spec:
        return

    inspect = manager.runtime.container_inspect(comfyui_spec.container)
    state = inspect.get("State") if isinstance(inspect, dict) else None
    is_running = False
    if isinstance(state, dict):
        is_running = bool(state.get("Running")) or state.get("Status") == "running"
    if not is_running:
        if verbose:
            console.print(
                "[info]ComfyUI container not running; skipping custom node requirements[/]"
            )
        return

    container_dir = _comfyui_custom_nodes_container_dir(comfyui_spec)
    container_id = None
    if isinstance(inspect, dict):
        container_id = inspect.get("Id") or inspect.get("ID")
    target_dir = f"{container_dir.rstrip('/')}/.airpods/site-packages"
    requirements = custom_nodes_module.collect_requirements(
        nodes, container_custom_nodes_dir=container_dir, container_id=container_id
    )
    if not requirements:
        return

    with status_spinner("Installing ComfyUI custom node requirements"):
        results = custom_nodes_module.install_requirements(
            runtime=manager.runtime,
            container_name=comfyui_spec.container,
            requirements=requirements,
            target_dir=target_dir,
            container_id=container_id,
        )

    installed = sum(
        1 for result in results if result.action in {"installed", "installed-user"}
    )
    fallbacks = [result for result in results if result.action == "installed-user"]
    errors = [result for result in results if result.action == "error"]

    if installed:
        console.print(f"[ok]Installed {installed} custom node requirement(s)[/]")
    elif verbose:
        console.print("[info]No custom node requirements installed[/]")

    if fallbacks:
        console.print(
            "[warn]Custom node requirements installed to user site-packages; "
            "reinstall if the container is recreated.[/]"
        )

    if errors:
        for result in errors:
            detail = f": {result.detail}" if result.detail else ""
            console.print(
                f"[warn]Custom node requirements failed for {result.name}{detail}[/]"
            )


def register(app: typer.Typer) -> CommandMap:
    @app.command(context_settings=COMMAND_CONTEXT)
    def start(
        ctx: typer.Context,
        help_: bool = command_help_option(),
        service: Optional[list[str]] = typer.Argument(
            None,
            help="Services to start (default: all).",
            metavar="service",
            shell_complete=service_name_completion,
        ),
        force_cpu: bool = typer.Option(
            False, "--cpu", help="Force CPU even if GPU is present."
        ),
        sequential: bool = typer.Option(
            False,
            "--sequential",
            help="Pull images sequentially (overrides cli.max_concurrent_pulls).",
        ),
        pre_fetch: bool = typer.Option(
            False,
            "--pre-fetch",
            help="Download service images without starting containers.",
        ),
        wait: bool = typer.Option(
            False,
            "--wait",
            help="Wait for HTTP health checks before returning (may take a while for some services).",
        ),
        yes: bool = typer.Option(
            False,
            "--yes",
            "-y",
            help="Skip confirmation prompts (auto-confirm downloads).",
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
        ensure_runtime_available()

        # Enable CUDA logging during startup flows
        import airpods.config as config_module

        config_module.ENABLE_COMFY_CUDA_LOG = True

        cli_config = get_cli_config()
        yes = yes or bool(getattr(cli_config, "auto_confirm", False))
        max_concurrent_pulls = 1 if sequential else cli_config.max_concurrent_pulls

        if pre_fetch:
            specs_for_download: list[ServiceSpec] = []
            for spec in specs:
                exists = manager.runtime.image_exists(spec.image)
                if exists is True:
                    continue
                specs_for_download.append(spec)
            if not specs_for_download:
                if verbose:
                    console.print("[ok]All requested images are already present[/]")
                return
            # Check for images that need to be downloaded and confirm with user
            if not yes:
                if not _confirm_image_downloads(specs_for_download):
                    console.print("[warn]Download cancelled by user[/]")
                    raise typer.Exit(code=0)
            _pull_images_with_progress(
                specs_for_download,
                max_concurrent=max_concurrent_pulls,
            )
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

        # Sync plugins even if services are already running.
        from airpods import plugins  # noqa: F401
        from airpods import custom_nodes as custom_nodes_module

        custom_nodes_list = (
            custom_nodes_module.get_custom_node_specs()
            if any(spec.name == "comfyui" for spec in specs)
            else []
        )
        custom_nodes_keep = custom_nodes_module.custom_nodes_keep_entries(
            custom_nodes_list
        )

        synced_webui, synced_comfyui = _maybe_sync_plugins(
            specs, verbose=verbose, keep_custom_nodes=custom_nodes_keep
        )
        custom_nodes_list, custom_nodes_prepared = _maybe_prepare_custom_nodes(
            specs, nodes=custom_nodes_list, verbose=verbose
        )

        # If everything is already running, still auto-import Open WebUI plugins and exit.
        if not needs_start:
            _maybe_import_webui_plugins(specs, cli_config=cli_config, verbose=verbose)
            _maybe_install_custom_node_requirements(
                specs, nodes=custom_nodes_list, verbose=verbose
            )
            if synced_comfyui > 0:
                console.print(
                    "[warn]ComfyUI is already running; restart is required to load updated custom nodes.[/]"
                )
            if custom_nodes_prepared > 0:
                console.print(
                    "[warn]ComfyUI is already running; restart is required to load newly installed custom nodes.[/]"
                )

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
        config = get_config()

        # Show GPU status (verbose only)
        if verbose:
            gpu_available, gpu_detail = detect_gpu()
            if gpu_available:
                console.print(f"GPU: [ok]enabled[/] ({gpu_detail})")
            else:
                console.print(f"GPU: [muted]not detected[/] ({gpu_detail})")
            if gpu_available and manager.gpu_device_flag is None:
                console.print(
                    "[warn]GPU passthrough not configured for the current runtime. "
                    "Set up NVIDIA CDI or force CPU.[/]"
                )

            # Show CUDA detection info if ComfyUI is being started
            comfyui_specs = [s for s in specs_to_start if s.name == "comfyui"]
            if comfyui_specs:
                has_gpu_cap, gpu_name_cap, compute_cap = (
                    detect_cuda_compute_capability()
                )
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
        else:
            gpu_available, gpu_detail = detect_gpu()

        with status_spinner("Ensuring volumes"):
            volume_results = manager.ensure_volumes(specs_to_start)
        print_volume_status(volume_results, verbose=verbose)

        for spec in specs_to_start:
            if spec.name == "comfyui":
                _ensure_comfyui_user_dirs(spec)

        # Plugins were already synced above for all requested services.

        # Simple log-based startup process
        service_urls: dict[str, str] = {}
        failed_services = []
        timeout_services = []

        def _effective_spec(spec: ServiceSpec) -> ServiceSpec:
            gpu_passthrough_ready = manager.gpu_device_flag is not None
            use_cpu_image = force_cpu or not gpu_available or not gpu_passthrough_ready
            if (
                spec.name == "llamacpp"
                and use_cpu_image
                and spec.cpu_image
                and spec.cpu_image != spec.image
            ):
                return replace(
                    spec,
                    image=spec.cpu_image,
                    needs_gpu=False,
                    force_cpu=True,
                )
            return spec

        specs_for_download: list[ServiceSpec] = []
        for spec in (_effective_spec(spec) for spec in specs_to_start):
            exists = manager.runtime.image_exists(spec.image)
            if exists is True:
                continue
            specs_for_download.append(spec)

        # Validate llama.cpp model presence before pulling images.
        needs_llamacpp = any(spec.name == "llamacpp" for spec in specs_to_start)
        llamacpp_cfg = config.services.get("llamacpp") if needs_llamacpp else None
        if llamacpp_cfg:
            model_arg = None
            if llamacpp_cfg.command_args:
                model_arg = llamacpp_cfg.command_args.get("model")
            if isinstance(model_arg, str) and model_arg.startswith("/models/"):
                rel = model_arg[len("/models/") :]
                host_models = state.resolve_volume_path("airpods_models/gguf")
                model_path = host_models / rel
                if not model_path.exists():
                    console.print(f"[warn]llamacpp model not found: {model_path}[/]")
                    if llamacpp_cfg.default_model_url:
                        console.print(
                            "[info]Default model is configured (small GGUF for most PCs).[/]"
                        )
                        if yes or ui.confirm_action(
                            "Download the default model now?", default=True
                        ):
                            try:
                                gguf.download_model(
                                    llamacpp_cfg.default_model_url, name=rel
                                )
                                console.print(
                                    f"[ok]Downloaded default model to {model_path}[/]"
                                )
                            except Exception as exc:
                                console.print(
                                    f"[error]Failed to download default model: {exc}[/]"
                                )
                                raise typer.Exit(code=1)
                        else:
                            console.print(
                                "[info]Download a GGUF file into the store, then retry:[/]"
                            )
                            console.print(
                                "[info]  airpods models gguf pull <url> --name "
                                f"{rel}[/]"
                            )
                            raise typer.Exit(code=1)
                    else:
                        console.print(
                            "[info]Download a GGUF file into the store, then retry:[/]"
                        )
                        console.print(
                            f"[info]  airpods models gguf pull <url> --name {rel}[/]"
                        )
                        raise typer.Exit(code=1)

        if specs_for_download:
            # Check for images that need to be downloaded and confirm with user
            if not yes:
                if not _confirm_image_downloads(specs_for_download):
                    console.print("[warn]Download cancelled by user[/]")
                    raise typer.Exit(code=0)

            # Pull images with live progress so long pulls don't feel like a hang.
            _pull_images_with_progress(
                specs_for_download, max_concurrent=max_concurrent_pulls, verbose=verbose
            )
        elif verbose:
            console.print("[info]Images already present; skipping pulls[/]")

        # Start services with simple logging
        for spec in specs_to_start:
            if verbose:
                console.print(f"Starting [accent]{spec.name}[/]...")

            try:
                with status_spinner(f"Launching {spec.name}"):
                    effective_spec = _effective_spec(spec)
                    if effective_spec is not spec:
                        if force_cpu:
                            message = "llamacpp: forcing CPU image."
                        elif not gpu_available:
                            message = (
                                "llamacpp GPU requested but no GPU detected; "
                                "falling back to CPU image."
                            )
                        else:
                            message = (
                                "llamacpp GPU passthrough not configured; "
                                "falling back to CPU image."
                            )
                        console.print(f"[warn]{message}[/]")

                    manager.start_service(
                        effective_spec,
                        gpu_available=gpu_available,
                        force_cpu_override=force_cpu,
                    )
                if verbose:
                    console.print(f"[ok]✓ {spec.name} launched[/]")
            except Exception as e:
                console.print(f"[error]✗ Failed to start {spec.name}: {e}[/]")
                failed_services.append(spec.name)
                continue

        # Install custom node requirements once ComfyUI is running.
        _maybe_install_custom_node_requirements(
            specs, nodes=custom_nodes_list, verbose=verbose
        )

        # If we're not waiting for readiness, return after pods are launched.
        if not wait:
            # Even without --wait, attempt to auto-import Open WebUI plugins once DB exists.
            _maybe_import_webui_plugins(specs, cli_config=cli_config, verbose=verbose)

            started = [
                spec.name for spec in specs_to_start if spec.name not in failed_services
            ]
            if started:
                console.print(
                    f"[ok]✓ Launched {len(started)} service{'s' if len(started) != 1 else ''}: {', '.join(started)}[/]"
                )
            if failed_services:
                console.print(
                    f"[error]✗ Failed services: {', '.join(failed_services)}. "
                    "Check logs with 'airpods logs'[/]"
                )
                raise typer.Exit(code=1)
            console.print(
                "[dim]Tip: Use 'airpods status' to check readiness and URLs, or 'airpods logs <service>' to watch startup.[/dim]"
            )

            try:
                from airpods.updates import (
                    check_for_update,
                    detect_install_source,
                    format_upgrade_hint,
                    is_update_available,
                )

                latest = check_for_update(timeout_seconds=0.8)
                if latest and is_update_available(latest):
                    hint = format_upgrade_hint(latest, detect_install_source())
                    console.print(
                        f"[warn]Update available:[/] {latest.tag} (installed: v{__version__})"
                    )
                    console.print(f"[dim]{hint}[/dim]")
            except Exception:
                pass
            return

        # Wait for health checks with timeout
        start_time = time.time()
        timeout_seconds = cli_config.startup_timeout
        check_interval = cli_config.startup_check_interval

        with status_spinner(
            f"Waiting for services to become ready (up to {timeout_seconds}s)"
        ) as status:
            while True:
                elapsed = time.time() - start_time
                if elapsed >= timeout_seconds:
                    break

                pod_rows = manager.pod_status_rows() or {}
                all_done = True
                pending: list[str] = []

                for spec in specs_to_start:
                    if spec.name in failed_services:
                        continue

                    if spec.name in service_urls:
                        continue  # Already healthy / ready

                    row = pod_rows.get(spec.pod)
                    if not row:
                        all_done = False
                        pending.append(spec.name)
                        continue

                    pod_status = (row.get("Status") or "").strip()

                    if pod_status in {"Exited", "Error"}:
                        if spec.name not in failed_services:
                            failed_services.append(spec.name)
                        continue

                    if pod_status != "Running":
                        all_done = False
                        pending.append(spec.name)
                        continue

                    port_bindings = manager.service_ports(spec)
                    host_ports = collect_host_ports(spec, port_bindings)
                    host_port = host_ports[0] if host_ports else None

                    if not spec.health_path or host_port is None:
                        # No health check needed; pod running is "ready".
                        if host_port:
                            service_urls[spec.name] = f"http://localhost:{host_port}"
                        else:
                            service_urls[spec.name] = ""
                        continue

                    if check_service_health(spec, host_port):
                        service_urls[spec.name] = f"http://localhost:{host_port}"
                    else:
                        all_done = False
                        pending.append(spec.name)

                if all_done:
                    break

                remaining = max(0, int(timeout_seconds - elapsed))
                if pending:
                    pending_label = ", ".join(pending)
                    status.update(
                        f"[info]Waiting ({remaining}s left): {pending_label}[/]"
                    )
                else:
                    status.update(f"[info]Waiting ({remaining}s left)[/]")

                time.sleep(check_interval)

        # Handle timeouts
        for spec in specs_to_start:
            if spec.name not in failed_services and spec.name not in service_urls:
                timeout_services.append(spec.name)

        # Categorize results
        healthy_services = [
            name for name in service_urls.keys() if name not in failed_services
        ]
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

        # Auto-pull Ollama models if configured and service is healthy
        ollama_specs = [s for s in specs_to_start if s.name == "ollama"]
        if (
            ollama_specs
            and "ollama" in service_urls
            and "ollama" not in failed_services
        ):
            from airpods import ollama as ollama_module
            from airpods.cli.common import get_ollama_port

            config = get_config()
            auto_pull = config.services.get("ollama", None)
            auto_pull_models = auto_pull.auto_pull_models if auto_pull else []

            if auto_pull_models:
                port = get_ollama_port()

                # Get list of installed models
                try:
                    installed = ollama_module.list_models(port)
                    installed_names = {m.get("name") for m in installed}

                    # Filter out models that are already installed
                    to_pull = [m for m in auto_pull_models if m not in installed_names]

                    if to_pull:
                        console.print(
                            f"[info]Auto-pulling {len(to_pull)} model(s)...[/]"
                        )

                        for model_name in to_pull:
                            try:
                                console.print(f"  Pulling [accent]{model_name}[/]...")
                                ollama_module.pull_model(model_name, port)
                                console.print(f"  [ok]✓ {model_name} ready[/]")
                            except Exception as e:
                                console.print(
                                    f"  [warn]Failed to pull {model_name}: {e}[/]"
                                )
                    elif verbose:
                        console.print("[info]All auto-pull models already installed[/]")

                except Exception as e:
                    console.print(f"[warn]Auto-pull failed: {e}[/]")

        # Auto-import plugins into Open WebUI if service is healthy
        if "open-webui" in service_urls and "open-webui" not in failed_services:
            _maybe_import_webui_plugins(specs, cli_config=cli_config, verbose=verbose)

    return {"start": start}


def _format_size(size_bytes: int) -> str:
    """Format bytes as human-readable size."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


def _parse_size_fragment(value: str, unit: str) -> int:
    multipliers = {
        "B": 1,
        "KB": 1024,
        "MB": 1024**2,
        "GB": 1024**3,
        "TB": 1024**4,
        "PB": 1024**5,
    }
    try:
        num = float(value)
    except ValueError:
        return 0
    factor = multipliers.get(unit.upper())
    if factor is None:
        return 0
    return int(num * factor)


def _confirm_image_downloads(specs: list[ServiceSpec]) -> bool:
    """Check for images to download and confirm with user.

    Returns True to proceed, False to cancel.
    """
    import shutil
    from rich.table import Table
    from rich.prompt import Confirm

    # Collect images that need to be downloaded
    to_download: list[tuple[str, str, int]] = []  # (service, image, size_bytes)

    with status_spinner("Checking images"):
        for spec in specs:
            # Check if image already exists locally
            if manager.runtime.image_exists(spec.image):
                continue

            # Try to get remote image size
            size_bytes = manager.runtime.get_remote_image_size(spec.image)

            # If we couldn't get size, use a placeholder
            if size_bytes is None:
                size_bytes = 0  # Will be marked as unknown

            to_download.append((spec.name, spec.image, size_bytes))

    # If no downloads needed, proceed
    if not to_download:
        return True

    # Get available disk space
    try:
        stat = shutil.disk_usage("/var/lib/containers")
    except (OSError, FileNotFoundError):
        # Fallback to root filesystem
        try:
            stat = shutil.disk_usage("/")
        except (OSError, FileNotFoundError):
            stat = None

    # Calculate total download size
    total_bytes = sum(size for _, _, size in to_download if size > 0)
    has_unknown_sizes = any(size == 0 for _, _, size in to_download)

    # Create borderless table
    table = Table(show_header=True, show_edge=False, show_lines=False, padding=(0, 2))
    table.add_column("Service", style="cyan", no_wrap=True)
    table.add_column("Image", style="dim")
    table.add_column("Size", justify="right", style="yellow")

    for service, image, size_bytes in to_download:
        # Truncate long image names
        display_image = image
        if len(display_image) > 45:
            display_image = f"{display_image[:42]}..."

        size_str = _format_size(size_bytes) if size_bytes > 0 else "unknown"
        table.add_row(service, display_image, size_str)

    console.print()
    console.print("[bold]Images to download:[/]")
    console.print(table)
    console.print()

    # Show total and available space
    if total_bytes > 0 and has_unknown_sizes:
        console.print(
            f"Total download: [yellow]at least {_format_size(total_bytes)}[/] (some sizes unknown)"
        )
    elif total_bytes > 0:
        console.print(f"Total download: [yellow]{_format_size(total_bytes)}[/]")
    elif has_unknown_sizes:
        console.print("Total download: [dim]unknown (size lookup failed)[/]")

    if stat:
        available = stat.free
        console.print(f"Available space: [green]{_format_size(available)}[/]")

        # Warn if insufficient space (with 10% buffer)
        if total_bytes > 0 and total_bytes * 1.1 > available:
            console.print(f"[warn]⚠ Warning: Download may exceed available space[/]")
    console.print()

    # Prompt for confirmation
    try:
        return Confirm.ask("Proceed with download?", default=True)
    except (KeyboardInterrupt, EOFError):
        console.print()
        return False


@dataclass(frozen=True)
class _PullEvent:
    kind: str
    task_id: int
    payload: str = ""


def _pull_images_with_progress(
    specs: list[ServiceSpec], *, max_concurrent: int, verbose: bool = False
) -> None:
    if not specs:
        console.print("[warn]No services enabled; nothing to initialize.[/]")
        return

    events: queue.Queue[_PullEvent] = queue.Queue()
    max_workers = max(1, max_concurrent)

    def _iter_pull_lines(stream: str):
        # Podman may emit carriage-return progress; normalize to line events.
        for chunk in stream.splitlines():
            for part in chunk.split("\r"):
                line = part.strip()
                if line:
                    yield line

    def _parse_download_progress(line: str) -> tuple[str, int, int | None] | None:
        # Expected patterns (docker/podman):
        # <layer>: Downloading 12.3MB/45.6MB
        # <layer>: Downloading [==>] 12.3MB/45.6MB
        match = re.match(r"^(?P<layer>[0-9a-f]{6,}):", line, re.IGNORECASE)
        if not match:
            return None
        layer = match.group("layer")
        size_match = re.search(
            r"(?P<cur>\d+(?:\.\d+)?)\s*(?P<cur_unit>[kKmMgGtTpP]?B)\s*/\s*"
            r"(?P<total>\d+(?:\.\d+)?)\s*(?P<total_unit>[kKmMgGtTpP]?B)",
            line,
        )
        if not size_match:
            return None
        current = _parse_size_fragment(
            size_match.group("cur"), size_match.group("cur_unit")
        )
        total = _parse_size_fragment(
            size_match.group("total"), size_match.group("total_unit")
        )
        if current <= 0:
            return None
        return layer, current, total if total > 0 else None

    def _is_noise_line(line: str) -> bool:
        lower = line.lower()
        return lower.startswith(
            (
                "copying blob",
                "copying",
                "pulling fs layer",
                "waiting",
                "extracting",
                "download complete",
                "pull complete",
                "already exists",
                "status:",
                "digest:",
            )
        )

    def _pull_one(spec: ServiceSpec, task_id: int) -> None:
        start = time.perf_counter()
        events.put(_PullEvent("start", task_id))
        runtime_cli = manager.runtime.runtime_name
        try:
            proc = subprocess.Popen(
                [runtime_cli, "pull", spec.image],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except OSError as exc:
            events.put(_PullEvent("error", task_id, str(exc)))
            return
        output: list[str] = []
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                output.append(raw)
                for line in _iter_pull_lines(raw):
                    events.put(_PullEvent("line", task_id, line))
        finally:
            rc = proc.wait()

        if rc != 0:
            detail = "".join(output).strip()
            events.put(_PullEvent("error", task_id, detail))
            return

        elapsed = time.perf_counter() - start
        size = manager.runtime.image_size(spec.image)
        transfer = format_transfer_label(size, elapsed) or f"{elapsed:.1f}s"
        events.put(_PullEvent("done", task_id, transfer))

    title = "[info]Pulling Images"
    if verbose:
        title = "[info]Pulling Images (live)"

    with Progress(
        SpinnerColumn(style="accent"),
        TextColumn("{task.fields[service]}", style="cyan", justify="right"),
        TextColumn("{task.fields[status]}", style="muted", markup=True),
        TextColumn("{task.fields[transfer]}", style="dim", justify="right"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        tasks: dict[int, ServiceSpec] = {}
        task_ids: dict[str, int] = {}
        progress_bytes: dict[int, dict[str, int]] = {}
        progress_totals: dict[int, dict[str, int]] = {}

        for spec in specs:
            task_id = progress.add_task(
                title,
                total=None,
                service=spec.name,
                status="Waiting…",
                transfer="",
            )
            tasks[task_id] = spec
            task_ids[spec.name] = task_id
            progress_bytes[task_id] = {}
            progress_totals[task_id] = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(_pull_one, spec, task_ids[spec.name]) for spec in specs
            ]

            failures: list[tuple[str, str]] = []
            done_count = 0
            while done_count < len(specs):
                try:
                    event = events.get(timeout=0.1)
                except queue.Empty:
                    continue

                if event.kind == "start":
                    progress.update(event.task_id, status="Pulling…", transfer="")
                elif event.kind == "line":
                    # Keep status compact; podman emits a lot of noise.
                    line = event.payload
                    parsed = _parse_download_progress(line)
                    if parsed is not None:
                        layer, current, total = parsed
                        progress_bytes[event.task_id][layer] = current
                        if total is not None:
                            progress_totals[event.task_id][layer] = total
                        downloaded = sum(progress_bytes[event.task_id].values())
                        if downloaded > 0:
                            total_known = sum(progress_totals[event.task_id].values())
                            if total_known > 0:
                                transfer = (
                                    f"Downloaded {_format_size(downloaded)}"
                                    f"/{_format_size(total_known)}"
                                )
                            else:
                                transfer = f"Downloaded {_format_size(downloaded)}"
                            progress.update(event.task_id, transfer=transfer)
                        continue
                    if _is_noise_line(line):
                        continue
                    if len(line) > 80:
                        line = f"{line[:77]}…"
                    progress.update(event.task_id, status=line)
                elif event.kind == "done":
                    progress.update(
                        event.task_id,
                        status="[ok]✓ Ready[/]",
                        transfer=event.payload,
                        total=1,
                        completed=1,
                    )
                    done_count += 1
                elif event.kind == "error":
                    spec = tasks.get(event.task_id)
                    failures.append((spec.name if spec else "unknown", event.payload))
                    progress.update(
                        event.task_id,
                        status="[error]✗ Failed[/]",
                        transfer="",
                        total=1,
                        completed=1,
                    )
                    done_count += 1

            for future in futures:
                future.result()

        if failures:
            for name, detail in failures:
                if detail:
                    trimmed = detail.strip()
                    if len(trimmed) > 500:
                        trimmed = f"{trimmed[:500]}…"
                    console.print(f"[error]{name} pull error:[/] {trimmed}")
                    if (
                        "manifest unknown" in trimmed
                        and "llama.cpp:server-cuda" in trimmed
                    ):
                        console.print(
                            "[info]Tip: switch to ghcr.io/ggml-org/llama.cpp:server "
                            "and let airpods derive the CUDA tag.[/]"
                        )
                else:
                    console.print(f"[error]{name} pull error:[/] unknown error")
            console.print("[error]✗ Failed to pull one or more images[/]")
            raise typer.Exit(code=1)
