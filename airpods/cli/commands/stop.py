"""Stop command implementation for gracefully stopping Podman containers."""

from __future__ import annotations

from typing import Optional

import typer

from airpods import ui
from airpods.logging import console

from ..common import (
    COMMAND_CONTEXT,
    get_cli_config,
    ensure_runtime_available,
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
            metavar="service",
            shell_complete=service_name_completion,
        ),
        remove: bool = typer.Option(
            False, "--remove", "-r", help="Remove pods after stopping."
        ),
        timeout: Optional[int] = typer.Option(
            None, "--timeout", "-t", help="Stop timeout seconds."
        ),
    ) -> None:
        """Stop pods for specified services; confirms before destructive removal."""
        maybe_show_command_help(ctx, help_)
        timeout = timeout if timeout is not None else get_cli_config().stop_timeout
        if timeout <= 0:
            raise typer.BadParameter("stop timeout must be positive")
        specs = resolve_services(service)
        ensure_runtime_available()

        # Check verbose mode from context
        verbose = is_verbose_mode(ctx)

        # Collect uptimes before stopping (only if verbose)
        uptimes: dict[str, str] = {}
        if verbose:
            for spec in specs:
                inspect = manager.runtime.container_inspect(spec.container)
                if (
                    inspect
                    and "State" in inspect
                    and "StartedAt" in inspect["State"]
                    and inspect["State"]["StartedAt"]
                ):
                    from airpods.cli.status_view import _format_uptime

                    started_at = inspect["State"]["StartedAt"]
                    uptimes[spec.name] = _format_uptime(started_at)
                else:
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
        already_stopped_services: list[str] = []

        pod_rows = manager.pod_status_rows() or {}

        def _is_pod_running(pod_name: str) -> bool:
            row = pod_rows.get(pod_name) or {}
            status = str(row.get("Status", "")).lower()
            return status.startswith("running")

        # Stop each service with simple logging
        for spec in specs:
            pod_exists = manager.runtime.pod_exists(spec.pod)
            is_running = _is_pod_running(spec.pod)

            if remove:
                if not pod_exists:
                    not_found_services.append(spec.name)
                    if verbose:
                        console.print(f"[warn]⊘ {spec.name} not found[/]")
                    continue

                if is_running:
                    if verbose:
                        uptime = uptimes.get(spec.name, "-")
                        console.print(
                            f"Stopping [accent]{spec.name}[/] (uptime: {uptime})..."
                        )
                elif verbose:
                    console.print(f"Removing [accent]{spec.name}[/]...")

                manager.stop_service(spec, remove=True, timeout=timeout)
                stopped_services.append(spec.name)
                if verbose:
                    console.print(f"[ok]✓ {spec.name} removed[/]")
                continue

            # remove == False
            if not is_running:
                if not pod_exists:
                    not_found_services.append(spec.name)
                    if verbose:
                        console.print(f"[warn]⊘ {spec.name} not found[/]")
                else:
                    already_stopped_services.append(spec.name)
                    if verbose:
                        console.print(f"[info]⊘ {spec.name} already stopped[/]")
                continue

            if verbose:
                uptime = uptimes.get(spec.name, "-")
                console.print(f"Stopping [accent]{spec.name}[/] (uptime: {uptime})...")

            existed = manager.stop_service(spec, remove=False, timeout=timeout)
            if not existed:
                not_found_services.append(spec.name)
                if verbose:
                    console.print(f"[warn]⊘ {spec.name} not found[/]")
            else:
                stopped_services.append(spec.name)
                if verbose:
                    console.print(f"[ok]✓ {spec.name} stopped[/]")

        # Calculate counts for summary
        stopped_count = len(stopped_services)
        not_found_count = len(not_found_services)
        already_stopped_count = len(already_stopped_services)

        action = "Removed" if remove else "Stopped"
        if stopped_count > 0:
            console.print(
                f"[ok]✓ {action} {stopped_count} service{'s' if stopped_count != 1 else ''}[/]"
            )

        if not_found_count > 0:
            console.print(
                f"[warn]⊘ {not_found_count} service{'s' if not_found_count != 1 else ''} not found[/]"
            )
        if already_stopped_count > 0 and not remove:
            console.print(
                f"[info]⊘ {already_stopped_count} service{'s' if already_stopped_count != 1 else ''} already stopped[/]"
            )

    return {"stop": stop}
