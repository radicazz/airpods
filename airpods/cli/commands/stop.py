"""Stop command implementation for gracefully stopping Podman containers."""

from __future__ import annotations

from typing import Optional

import typer

from airpods import ui
from airpods.logging import console

from ..common import (
    COMMAND_CONTEXT,
    DEFAULT_STOP_TIMEOUT,
    ensure_podman_available,
    is_verbose_mode,
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

        # Check verbose mode from context
        verbose = is_verbose_mode(ctx)

        # Collect uptimes before stopping (only if verbose or needed for summary)
        uptimes: dict[str, str] = {}
        total_uptime_seconds = 0
        for spec in specs:
            try:
                import subprocess

                result = subprocess.run(
                    [
                        "podman",
                        "container",
                        "inspect",
                        spec.container,
                        "--format",
                        "{{.State.StartedAt}}",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode == 0 and result.stdout.strip():
                    from airpods.cli.status_view import _format_uptime

                    started_at = result.stdout.strip()
                    uptimes[spec.name] = _format_uptime(started_at)

                    # Calculate total seconds for summary
                    from datetime import datetime

                    parts = started_at.split()
                    if len(parts) >= 2:
                        dt_str = f"{parts[0]} {parts[1].split('.')[0]}"
                        # Skip invalid/epoch timestamps
                        if not dt_str.startswith("0001-"):
                            started = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                            now = datetime.now()
                            delta = now - started
                            total_uptime_seconds += int(delta.total_seconds())
            except Exception:
                uptimes[spec.name] = "-"

        if remove and specs:
            lines = "\n".join(f"  - {spec.name} ({spec.pod})" for spec in specs)
            prompt = (
                "Removing pods will delete running containers (volumes stay intact).\n"
                f"{lines}\nProceed with removal?"
            )
            if not ui.confirm_action(prompt, default=False):
                console.print("[warn]Stop cancelled by user.[/]")
                raise typer.Abort()

        # Simple log-based stopping process
        stopped_services = []
        not_found_services = []

        # Stop each service with simple logging
        for spec in specs:
            if verbose:
                uptime = uptimes.get(spec.name, "-")
                console.print(f"Stopping [accent]{spec.name}[/] (uptime: {uptime})...")
            else:
                console.print(f"Stopping [accent]{spec.name}[/]...")
            
            existed = manager.stop_service(spec, remove=remove, timeout=timeout)
            if not existed:
                not_found_services.append(spec.name)
                if verbose:
                    console.print(f"[warn]⊘ {spec.name} not found[/]")
            else:
                stopped_services.append(spec.name)
                if verbose:
                    action = "removed" if remove else "stopped"
                    console.print(f"[ok]✓ {spec.name} {action}[/]")

        # Calculate counts for summary
        stopped_count = len(stopped_services)
        not_found_count = len(not_found_services)

        action = "Removed" if remove else "Stopped"
        if stopped_count > 0:
            total_uptime_display = ""
            if total_uptime_seconds > 0:
                from airpods.cli.status_view import _format_uptime
                from datetime import datetime

                fake_start = datetime.now().timestamp() - total_uptime_seconds
                fake_str = datetime.fromtimestamp(fake_start).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                total_display = _format_uptime(fake_str + " -0500 EST")
                total_uptime_display = f" • Total uptime: [accent]{total_display}[/]"

            console.print(
                f"[ok]✓ {action} {stopped_count} service{'s' if stopped_count != 1 else ''}{total_uptime_display}[/]"
            )

        if not_found_count > 0:
            console.print(
                f"[warn]⊘ {not_found_count} service{'s' if not_found_count != 1 else ''} not found[/]"
            )

    return {"stop": stop}
