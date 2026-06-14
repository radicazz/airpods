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
