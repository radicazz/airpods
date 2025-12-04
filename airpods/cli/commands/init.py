"""Init command for initial setup, volume creation, and image pulling."""

from __future__ import annotations

import typer
from rich.live import Live
from rich.spinner import Spinner
from rich.table import Table

from airpods import state, ui
from airpods.logging import console, status_spinner

from ..common import COMMAND_CONTEXT, manager, print_network_status, print_volume_status
from ..help import command_help_option, maybe_show_command_help
from ..type_defs import CommandMap


def register(app: typer.Typer) -> CommandMap:
    @app.command(context_settings=COMMAND_CONTEXT)
    def init(
        ctx: typer.Context,
        help_: bool = command_help_option(),
    ) -> None:
        """Verify tools, ensure resources, and report whether anything new was created."""
        maybe_show_command_help(ctx, help_)
        report = manager.report_environment()
        ui.show_environment(report)

        if report.missing:
            console.print(
                f"[error]The following dependencies are required: {', '.join(report.missing)}. Install them and re-run init.[/]"
            )
            raise typer.Exit(code=1)

        with status_spinner("Ensuring network"):
            network_created = manager.ensure_network()
        print_network_status(network_created, manager.network_name)

        specs = manager.resolve(None)

        with status_spinner("Ensuring volumes"):
            volume_results = manager.ensure_volumes(specs)
        print_volume_status(volume_results)

        image_states: dict[str, str] = {spec.name: "pending" for spec in specs}

        def _make_table() -> Table:
            """Create the live-updating image pull table."""
            table = Table(
                title="[info]Pulling Images", show_header=True, header_style="bold"
            )
            table.add_column("Service", style="cyan")
            table.add_column("Image", style="dim")
            table.add_column("Status", style="")

            for spec in specs:
                state_val = image_states[spec.name]
                if state_val == "pending":
                    table.add_row(spec.name, spec.image, "[dim]Waiting...")
                elif state_val == "pulling":
                    spinner = Spinner("dots", style="info")
                    table.add_row(spec.name, spec.image, spinner)
                elif state_val == "done":
                    table.add_row(spec.name, spec.image, "[ok]✓ Ready")

            return table

        with Live(_make_table(), refresh_per_second=4, console=console) as live:

            def _image_progress(phase, index, _total_count, spec):
                if phase == "start":
                    image_states[spec.name] = "pulling"
                else:
                    image_states[spec.name] = "done"
                live.update(_make_table())

            manager.pull_images(specs, progress_callback=_image_progress)

        with status_spinner("Preparing Open WebUI secret"):
            secret = state.ensure_webui_secret()
        console.print(
            f"[info]Open WebUI secret stored at {state.webui_secret_path()}[/]"
        )

        ui.success_panel("init complete. pods are ready to start.")

    return {"init": init}
