"""Doctor command for environment diagnostics and dependency checks."""

from __future__ import annotations

import typer

import os
from pathlib import Path

from airpods import __version__, gpu as gpu_utils, ui
import airpods.config as config_module
from airpods.configuration import get_config
from airpods.logging import console
from airpods.system import detect_cuda_compute_capability
from airpods.updates import (
    check_for_update,
    detect_install_source,
    format_upgrade_hint,
    is_update_available,
)
from airpods.cuda import select_cuda_version, get_cuda_info_display

from ..common import COMMAND_CONTEXT, DOCTOR_REMEDIATIONS, manager
from ..help import command_help_option, maybe_show_command_help
from ..type_defs import CommandMap

_LEGACY_UI_IMPORTS = (
    "/scripts/ui.js",
    "/extensions/core/groupNode.js",
    "/scripts/ui/components/buttonGroup.js",
    "/scripts/ui/components/button.js",
)


def _scan_for_legacy_ui_imports(root: Path) -> list[tuple[Path, list[str]]]:
    if not root.exists():
        return []
    matches: list[tuple[Path, list[str]]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in {".js", ".mjs"}:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hits = [pattern for pattern in _LEGACY_UI_IMPORTS if pattern in content]
        if hits:
            matches.append((path, hits))
    return matches


def register(app: typer.Typer) -> CommandMap:
    @app.command(context_settings=COMMAND_CONTEXT)
    def doctor(
        ctx: typer.Context,
        help_: bool = command_help_option(),
    ) -> None:
        """Re-run environment checks without mutating resources."""
        maybe_show_command_help(ctx, help_)

        report = manager.report_environment()
        ui.show_environment(report)

        # Show CUDA detection info
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

        # Check GPU passthrough setup (NVIDIA Container Toolkit + CDI)
        toolkit_installed, toolkit_version = gpu_utils.detect_nvidia_container_toolkit()
        if toolkit_installed:
            console.print(f"NVIDIA Container Toolkit: [ok]{toolkit_version}[/]")

            # Check CDI configuration
            if gpu_utils.check_cdi_available():
                console.print("NVIDIA CDI: [ok]configured[/]")
            else:
                console.print("NVIDIA CDI: [warn]not configured[/]")
                console.print("[dim]GPU pass-through may not work. Run:[/]")
                console.print(
                    "[dim]  sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml[/]"
                )
        else:
            console.print(f"NVIDIA Container Toolkit: [warn]{toolkit_version}[/]")
            if has_gpu_cap:
                console.print(
                    "[dim]GPU detected but Container Toolkit not found. Install it for GPU support in containers.[/]"
                )

        latest = check_for_update()
        if latest and is_update_available(latest):
            hint = format_upgrade_hint(latest, detect_install_source())
            console.print(
                f"[warn]Update available:[/] {latest.tag} (installed: v{__version__})"
            )
            console.print(f"[dim]{hint}[/dim]")

        if report.missing:
            console.print("[error]Missing dependencies detected:[/]")
            for dep in report.missing:
                guidance = DOCTOR_REMEDIATIONS.get(
                    dep, "Install it or ensure it is on your PATH."
                )
                console.print(f"[error]- {dep}[/] {guidance}")
            console.print(
                "[error]Resolve the missing dependencies and re-run doctor.[/]"
            )
            raise typer.Exit(code=1)

        config = get_config()
        llamacpp = config.services.get("llamacpp")
        if llamacpp and llamacpp.enabled:
            spec = config_module.REGISTRY.get("llamacpp")
            console.print("[info]llamacpp checks:[/]")

            if spec:
                if manager.runtime.image_exists(spec.image):
                    console.print(f"[ok]llamacpp image present: {spec.image}[/]")
                else:
                    console.print(
                        f"[warn]llamacpp image not pulled yet: {spec.image}[/]"
                    )
                if spec.cpu_image and spec.cpu_image != spec.image:
                    if not manager.runtime.image_exists(spec.cpu_image):
                        console.print(
                            f"[warn]llamacpp CPU image not pulled: {spec.cpu_image}[/]"
                        )

            llamacpp_ports = {p.host for p in llamacpp.ports}
            for name, service in config.services.items():
                if name == "llamacpp" or not service.enabled:
                    continue
                for mapping in service.ports:
                    if mapping.host in llamacpp_ports:
                        console.print(
                            f"[warn]llamacpp port conflict: {mapping.host} also used by {name}[/]"
                        )

            from airpods.state import state_root

            gguf_path = state_root() / "volumes" / "airpods_models" / "gguf"
            if gguf_path.exists():
                writable = os.access(gguf_path, os.W_OK)
            else:
                writable = os.access(gguf_path.parent, os.W_OK)
            if writable:
                console.print(f"[ok]GGUF store writable: {gguf_path}[/]")
            else:
                console.print(f"[warn]GGUF store not writable: {gguf_path}[/]")

        custom_nodes_dir = state_root() / "volumes" / "comfyui_custom_nodes"
        legacy_hits = _scan_for_legacy_ui_imports(custom_nodes_dir)
        if legacy_hits:
            console.print(
                "[warn]ComfyUI custom nodes using deprecated UI imports detected:[/]"
            )
            for path, hits in legacy_hits:
                try:
                    display = path.relative_to(custom_nodes_dir)
                except ValueError:
                    display = path
                console.print(f"[warn]- {display}: {', '.join(hits)}[/]")
            console.print(
                "[dim]Update or remove the extensions above to silence warnings.[/]"
            )

        ui.success_panel("doctor complete: environment ready.")

    return {"doctor": doctor}
