"""Start command implementation for launching Podman containers."""

from __future__ import annotations

from typing import Optional

import typer

from airpods import ui
from airpods.logging import console, status_spinner, step_progress
from airpods.system import detect_gpu
from airpods.services import ServiceStartResult, VolumeEnsureResult

from ..common import (
    COMMAND_CONTEXT,
    ensure_podman_available,
    manager,
    print_network_status,
    print_volume_status,
    resolve_services,
)
from ..completions import service_name_completion
from ..help import command_help_option, maybe_show_command_help
from ..type_defs import CommandMap


def _print_service_start_status(result: ServiceStartResult) -> None:
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
        spec_count = len(specs)
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

        with step_progress("Pulling images", total=spec_count) as progress:

            def _image_progress(phase, index, _total_count, spec):
                label = f"{spec.name} ({spec.image})"
                if phase == "start":
                    progress.start(index, label)
                else:
                    progress.advance()

            manager.pull_images(specs, progress_callback=_image_progress)

        existing_containers = [spec for spec in specs if manager.container_exists(spec)]
        if existing_containers and not force:
            lines = "\n".join(
                f"  - {spec.name} ({spec.container})" for spec in existing_containers
            )
            prompt = (
                f"Replace the following running containers before starting?\n{lines}"
            )
            if not ui.confirm_action(prompt, default=False):
                console.print("[warn]Start cancelled by user.[/]")
                raise typer.Abort()

        with step_progress("Starting services", total=spec_count) as progress:
            for index, spec in enumerate(specs, start=1):
                progress.start(index, spec.name)
                result = manager.start_service(
                    spec, gpu_available=gpu_available, force_cpu=force_cpu
                )
                progress.advance()
                _print_service_start_status(result)
                console.print(f"[ok]{spec.name} running in pod {spec.pod}[/]")
        ui.success_panel(f"start complete: {', '.join(spec.name for spec in specs)}")

    return {"start": start}
