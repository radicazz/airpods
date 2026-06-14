"""Startup orchestration helpers for the `airpods start` flow.

Contains the plugin sync / auto-import, ComfyUI custom node preparation
and in-container requirements installation, comfy workspace dir pre-creation,
and the Open WebUI DB readiness probe. These were extracted from the
monolithic start command (airpods/cli/commands/start.py) so that the
core launch/session logic can live in a focused module while the Typer
command surface stays thin.

These helpers still rely on the CLI manager proxy and rich console/status
for messaging and side effects; they are not intended as a general library
API yet.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from airpods.cli.common import manager
from airpods.logging import console, status_spinner
from airpods.services import ServiceSpec

# NOTE: CLIConfig and CustomNodeInstall are only used in annotations and
# are kept as strings or imported inside the small number of functions that
# need the real symbol (matching the pre-extraction style).


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
    # ports is List[Tuple[host_port, container_port]]; first mapping is the HTTP port
    webui_port = webui_specs[0].ports[0][0] if webui_specs[0].ports else 3000
    base_url = f"http://localhost:{webui_port}"
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
            if imported:
                console.print(
                    f"[ok]✓ Auto-imported {len(imported)} plugin(s) into Open WebUI[/]"
                )
                token = plugins._webui_signin(
                    base_url,
                    plugins.DEFAULT_ADMIN_EMAIL,
                    plugins.DEFAULT_ADMIN_PASSWORD,
                )
                if token:
                    reloaded = plugins.reload_functions_via_api(
                        base_url, token, imported
                    )
                    if verbose:
                        console.print(
                            f"[info]Reloaded {reloaded}/{len(imported)} plugin(s) into OWU memory[/]"
                        )
                elif verbose:
                    console.print(
                        "[info]Plugin hot-reload skipped — if you changed the admin "
                        "password, restart OWU to activate new plugins[/]"
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


def perform_start(
    specs_to_start: list[ServiceSpec],
    *,
    cli_config: "CLIConfig",
    verbose: bool,
    wait: bool,
    force_cpu: bool,
    yes: bool,
    max_concurrent_pulls: int,
    manager: object | None = None,
) -> None:
    """Core orchestration for starting the requested (and needed) services.

    This encapsulates GPU display, llama preflight+GGUF download, image pulls,
    the launch loop with effective spec/CPU fallback, the --wait readiness
    polling, summaries, auto Ollama model pulls, final post-start hooks
    (plugin import, custom node reqs), and the post-start update hint.

    Called by the thin start command after it has done first-run config
    creation, resolve, early already-running detection + initial sync/prepare,
    and volume ensure for the to-start set.
    """
    # Use the passed manager or fall back to the cli proxy (for tests / IoC prep)
    mgr = manager or __import__("airpods.cli.common", fromlist=["manager"]).manager

    from airpods import ui
    from airpods import __version__ as _airpods_version
    from airpods.system import detect_gpu, detect_cuda_compute_capability
    from airpods.cuda import select_cuda_version, get_cuda_info_display
    from airpods.configuration import get_config
    from airpods import gguf, state
    from airpods.ollama import format_size as _format_size  # not directly needed here
    from airpods.cli.common import get_ollama_port
    from airpods.cli import pull as _pull_cli

    # Show GPU status (verbose only)
    if verbose:
        gpu_available, gpu_detail = detect_gpu()
        if gpu_available:
            console.print(f"GPU: [ok]enabled[/] ({gpu_detail})")
        else:
            console.print(f"GPU: [muted]not detected[/] ({gpu_detail})")
        if gpu_available and getattr(mgr, "gpu_device_flag", None) is None:
            console.print(
                "[warn]GPU passthrough not configured for the current runtime. "
                "Set up NVIDIA CDI or force CPU.[/]"
            )

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
    else:
        gpu_available, gpu_detail = detect_gpu()

    # NOTE: volumes ensure is performed by the caller (command) before delegation
    # so that the "Ensuring volumes" status message stays in the start UX.

    # Simple log-based startup process
    service_urls: dict[str, str] = {}
    failed_services: list[str] = []
    timeout_services: list[str] = []

    def _effective_spec(spec: ServiceSpec) -> ServiceSpec:
        gpu_passthrough_ready = getattr(mgr, "gpu_device_flag", None) is not None
        use_cpu_image = force_cpu or not gpu_available or not gpu_passthrough_ready
        if (
            spec.name == "llamacpp"
            and use_cpu_image
            and getattr(spec, "cpu_image", None)
            and spec.cpu_image != spec.image
        ):
            from dataclasses import replace as _replace

            return _replace(
                spec,
                image=spec.cpu_image,
                needs_gpu=False,
                force_cpu=True,
            )
        return spec

    # The llama model presence guard + prompt was executed by the caller
    # (before image download decision) so that the prompt appears at the
    # natural point in the start UX.  Here we only deal with the images that
    # the caller decided need pulling.

    # (In a fuller extraction the llama guard could move here too; for the
    # initial split we keep the prompt timing identical by leaving it in the
    # thin command.)

    specs_for_download: list[ServiceSpec] = []
    for spec in (_effective_spec(spec) for spec in specs_to_start):
        exists = mgr.runtime.image_exists(spec.image)
        if exists is True:
            continue
        specs_for_download.append(spec)

    if specs_for_download:
        # Check for images that need to be downloaded and confirm with user
        if not yes:
            if not _pull_cli._confirm_image_downloads(specs_for_download):
                console.print("[warn]Download cancelled by user[/]")
                raise __import__("typer").Exit(code=0)

        # Pull images with live progress so long pulls don't feel like a hang.
        _pull_cli._pull_images_with_progress(
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

                mgr.start_service(
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

    # If we're not waiting for readiness, return after pods are launched.
    if not wait:
        # Even without --wait, attempt to auto-import Open WebUI plugins once DB exists.
        _launch._maybe_import_webui_plugins(
            specs, cli_config=cli_config, verbose=verbose
        )
        _launch._maybe_install_custom_node_requirements(
            specs,
            nodes=[],
            verbose=verbose,  # caller already prepared the list if needed
        )

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
            raise __import__("typer").Exit(code=1)
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
                    f"[warn]Update available:[/] {latest.tag} (installed: v{_airpods_version})"
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

            pod_rows = mgr.pod_status_rows() or {}
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

                port_bindings = mgr.service_ports(spec)
                host_ports = __import__(
                    "airpods.cli.status_view", fromlist=["collect_host_ports"]
                ).collect_host_ports(spec, port_bindings)
                host_port = host_ports[0] if host_ports else None

                if not spec.health_path or host_port is None:
                    # No health check needed; pod running is "ready".
                    if host_port:
                        service_urls[spec.name] = f"http://localhost:{host_port}"
                    else:
                        service_urls[spec.name] = ""
                    continue

                if __import__(
                    "airpods.cli.status_view", fromlist=["check_service_health"]
                ).check_service_health(
                    spec, host_port, timeout=cli_config.ping_timeout
                ):
                    service_urls[spec.name] = f"http://localhost:{host_port}"
                else:
                    all_done = False
                    pending.append(spec.name)

            if all_done:
                break

            remaining = max(0, int(timeout_seconds - elapsed))
            if pending:
                pending_label = ", ".join(pending)
                status.update(f"[info]Waiting ({remaining}s left): {pending_label}[/]")
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
        raise __import__("typer").Exit(code=1)

    if timeout_services:
        console.print(
            f"[warn]⏱ Timed out services: {', '.join(timeout_services)}. "
            "Services may still be starting. Check with 'airpods status'[/]"
        )

    # Auto-pull Ollama models if configured and service is healthy
    ollama_specs = [s for s in specs_to_start if s.name == "ollama"]
    if ollama_specs and "ollama" in service_urls and "ollama" not in failed_services:
        from airpods import ollama as ollama_module

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
                    console.print(f"[info]Auto-pulling {len(to_pull)} model(s)...[/]")

                    for model_name in to_pull:
                        try:
                            _pull_cli._pull_ollama_model_with_progress(
                                model_name, port, ollama_module
                            )
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
        _launch._maybe_import_webui_plugins(
            specs, cli_config=cli_config, verbose=verbose
        )

    # Re-attempt after readiness checks so requirements are installed when
    # ComfyUI startup is slower than container launch.
    _launch._maybe_install_custom_node_requirements(specs, nodes=[], verbose=verbose)
