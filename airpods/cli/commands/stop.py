"""Stop command implementation for gracefully stopping Podman containers."""

from __future__ import annotations

from typing import Optional

import typer

from airpods import ui
from airpods.logging import console, step_progress

from ..common import (
    COMMAND_CONTEXT,
    DEFAULT_STOP_TIMEOUT,
    ensure_podman_available,
    manager,
    resolve_services,
)
from ..type_defs import CommandMap


def register(app: typer.Typer) -> CommandMap:
    @app.command(context_settings=COMMAND_CONTEXT)
    def stop(
        service: Optional[list[str]] = typer.Argument(
            None, help="Services to stop (default: all)."
        ),
        remove: bool = typer.Option(
            False, "--remove", "-r", help="Remove pods after stopping."
        ),
        timeout: int = typer.Option(
            DEFAULT_STOP_TIMEOUT, "--timeout", "-t", help="Stop timeout seconds."
        ),
    ) -> None:
        """Stop pods for specified services; confirms before destructive removal."""
        specs = resolve_services(service)
        spec_count = len(specs)
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
        with step_progress("Stopping services", total=spec_count) as progress:
            for index, spec in enumerate(specs, start=1):
                progress.start(index, spec.name)
                existed = manager.stop_service(spec, remove=remove, timeout=timeout)
                progress.advance()
                if not existed:
                    console.print(f"[warn]{spec.pod} not found; skipping[/]")
                    continue
                console.print(f"[ok]{spec.name} stopped[/]")
        ui.success_panel(f"stop complete: {', '.join(spec.name for spec in specs)}")

    return {"stop": stop}
