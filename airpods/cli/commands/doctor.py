"""Doctor command for environment diagnostics and dependency checks."""

from __future__ import annotations

import typer

from airpods import ui
from airpods.logging import console
from airpods.system import detect_cuda_compute_capability
from airpods.cuda import select_cuda_version, get_cuda_info_display

from ..common import COMMAND_CONTEXT, DOCTOR_REMEDIATIONS, manager
from ..help import command_help_option, maybe_show_command_help
from ..type_defs import CommandMap


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
