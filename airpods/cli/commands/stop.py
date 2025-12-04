"""Stop command implementation for gracefully stopping Podman containers."""

from __future__ import annotations

from typing import Optional

import typer
from rich.live import Live
from rich.spinner import Spinner
from rich.table import Table

from airpods import ui
from airpods.logging import console

from ..common import (
    COMMAND_CONTEXT,
    DEFAULT_STOP_TIMEOUT,
    ensure_podman_available,
    manager,
    resolve_services,
)
from ..completions import service_name_completion
from ..help import command_help_option, maybe_show_command_help
from ..type_defs import CommandMap


def register(app: typer.Typer) -> CommandMap:
    @app.command(context_settings=COMMAND_CONTEXT)
    def stop(
        ctx: typer.Context,
        help_: bool = command_help_option(),
        service: Optional[list[str]] = typer.Argument(
            None,
            help="Services to stop (default: all).",
            shell_complete=service_name_completion,
        ),
        remove: bool = typer.Option(
            False, "--remove", "-r", help="Remove pods after stopping."
        ),
        timeout: int = typer.Option(
            DEFAULT_STOP_TIMEOUT, "--timeout", "-t", help="Stop timeout seconds."
        ),
    ) -> None:
        """Stop pods for specified services; confirms before destructive removal."""
        maybe_show_command_help(ctx, help_)
        specs = resolve_services(service)
        ensure_podman_available()
        if remove and specs:
            lines = "\n".join(f"  - {spec.name} ({spec.pod})" for spec in specs)
            prompt = (
                "Removing pods will delete running containers (volumes stay intact).\n"
                f"{lines}\nProceed with removal?"
            )
            if not ui.confirm_action(prompt, default=False):
                console.print("[warn]Stop cancelled by user.[/]")
                raise typer.Abort()

        service_states: dict[str, str] = {spec.name: "stopping" for spec in specs}

        def _make_table() -> Table:
            """Create the live-updating status table."""
            table = Table(
                title="[info]Stopping Services", show_header=True, header_style="bold"
            )
            table.add_column("Service", style="cyan")
            table.add_column("Status", style="")

            for spec in specs:
                state = service_states[spec.name]
                if state == "stopping":
                    spinner = Spinner("dots", style="info")
                    table.add_row(spec.name, spinner)
                elif state == "stopped":
                    table.add_row(spec.name, "[ok]✓ Stopped")
                elif state == "removed":
                    table.add_row(spec.name, "[ok]✓ Removed")
                elif state == "not_found":
                    table.add_row(spec.name, "[warn]⊘ Not found")

            return table

        with Live(_make_table(), refresh_per_second=4, console=console) as live:
            for spec in specs:
                existed = manager.stop_service(spec, remove=remove, timeout=timeout)
                if not existed:
                    service_states[spec.name] = "not_found"
                elif remove:
                    service_states[spec.name] = "removed"
                else:
                    service_states[spec.name] = "stopped"
                live.update(_make_table())

    return {"stop": stop}
