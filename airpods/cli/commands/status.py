"""Status command implementation for displaying pod health and availability."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

import typer

from airpods.logging import console

from ..common import (
    COMMAND_CONTEXT,
    ensure_runtime_available,
    is_verbose_mode,
    resolve_services,
)
from ..completions import service_name_completion
from ..help import command_help_option, maybe_show_command_help
from ..status_view import render_status
from ..type_defs import CommandMap


def register(app: typer.Typer) -> CommandMap:
    @app.command(context_settings=COMMAND_CONTEXT)
    def status(
        ctx: typer.Context,
        help_: bool = command_help_option(),
        service: Optional[list[str]] = typer.Argument(
            None,
            help="Services to report (default: all).",
            metavar="service",
            shell_complete=service_name_completion,
        ),
        watch: Optional[float] = typer.Option(
            None, "--watch", "-w", help="Refresh interval in seconds."
        ),
    ) -> None:
        """Show pod status."""
        maybe_show_command_help(ctx, help_)
        specs = resolve_services(service)
        ensure_runtime_available()
        if watch is not None and watch <= 0:
            raise typer.BadParameter("watch interval must be positive.")

        def _run_once() -> None:
            render_status(specs, show_legend=is_verbose_mode(ctx))

        if watch is None:
            _run_once()
            return

        try:
            while True:
                console.clear()
                _run_once()
                console.print(
                    f"[dim]Refreshed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (Ctrl+C to stop)[/]"
                )
                time.sleep(watch)
        except KeyboardInterrupt:
            console.print("[info]Stopped watching status.")

    return {"status": status}
