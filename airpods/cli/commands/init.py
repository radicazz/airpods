"""Init command for initial setup, volume creation, and image pulling."""

from __future__ import annotations

import typer

from typing import Iterable

from airpods import state, ui
from airpods.logging import console, status_spinner, step_progress
from airpods.services import VolumeEnsureResult

from ..common import COMMAND_CONTEXT, manager
from ..type_defs import CommandMap


def _print_network_status(created: bool) -> None:
    if created:
        console.print(f"[ok]Created network {manager.network_name}[/]")
    else:
        console.print(
            f"[info]Network {manager.network_name} already exists; reusing[/]"
        )


def _print_volume_status(results: Iterable[VolumeEnsureResult]) -> None:
    for result in results:
        label = "bind mount" if result.kind == "bind" else "volume"
        if result.created:
            console.print(f"[ok]Created {label} {result.source} -> {result.target}")
        else:
            console.print(
                f"[info]{label.capitalize()} {result.source} already exists; reusing"
            )


def register(app: typer.Typer) -> CommandMap:
    @app.command(context_settings=COMMAND_CONTEXT)
    def init() -> None:
        """Verify tools, ensure resources, and report whether anything new was created."""
        report = manager.report_environment()
        ui.show_environment(report)

        if report.missing:
            console.print(
                f"[error]The following dependencies are required: {', '.join(report.missing)}. Install them and re-run init.[/]"
            )
            raise typer.Exit(code=1)

        with status_spinner("Ensuring network"):
            network_created = manager.ensure_network()
        _print_network_status(network_created)

        specs = manager.resolve(None)

        with status_spinner("Ensuring volumes"):
            volume_results = manager.ensure_volumes(specs)
        _print_volume_status(volume_results)

        with step_progress("Pulling images", total=len(specs)) as progress:

            def _image_progress(phase, index, _total_count, spec):
                label = f"{spec.name} ({spec.image})"
                if phase == "start":
                    progress.start(index, label)
                else:
                    progress.advance()

            manager.pull_images(specs, progress_callback=_image_progress)

        with status_spinner("Preparing Open WebUI secret"):
            secret = state.ensure_webui_secret()
        console.print(
            f"[info]Open WebUI secret stored at {state.webui_secret_path()}[/]"
        )

        ui.success_panel("init complete. pods are ready to start.")

    return {"init": init}
