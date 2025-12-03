"""Doctor command for environment diagnostics and dependency checks."""

from __future__ import annotations

import typer

from airpods import ui
from airpods.logging import console

from ..common import COMMAND_CONTEXT, DOCTOR_REMEDIATIONS, manager
from ..help import show_command_help
from ..type_defs import CommandMap


def register(app: typer.Typer) -> CommandMap:
    @app.command(context_settings={**COMMAND_CONTEXT, "help_option_names": []})
    def doctor(
        ctx: typer.Context,
        help_: bool = typer.Option(
            False,
            "--help",
            "-h",
            help="Show this message and exit.",
            is_eager=True,
        ),
    ) -> None:
        """Re-run environment checks without mutating resources."""
        if help_:
            show_command_help(ctx)
            raise typer.Exit()

        report = manager.report_environment()
        ui.show_environment(report)

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

        ui.success_panel("doctor complete: environment ready.")

    return {"doctor": doctor}
