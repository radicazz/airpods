"""UI utilities for consistently themed Rich console output."""

from __future__ import annotations

from typing import Tuple

import typer
from rich import box
from rich.console import RenderableType
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from airpods.logging import PALETTE, console
from airpods.services import EnvironmentReport

DEFAULT_ROW_STYLES: Tuple[str, str] | None = None


def themed_table(
    *,
    title: str | None = None,
    show_header: bool = True,
    header_style: str | None = None,
    row_styles: Tuple[str, str] | None = DEFAULT_ROW_STYLES,
    box_style=box.SIMPLE_HEAD,
    pad_edge: bool = False,
    expand: bool = False,
) -> Table:
    """Return a Rich Table with shared palette + layout defaults."""
    return Table(
        title=title,
        show_header=show_header,
        header_style=header_style or f"bold {PALETTE['blue']}",
        style=PALETTE["fg"],
        row_styles=row_styles,
        box=box_style,
        pad_edge=pad_edge,
        expand=expand,
    )


def themed_grid(*, padding: Tuple[int, int] = (0, 3), expand: bool = False) -> Table:
    """Return a Rich grid table honoring the shared palette."""
    table = Table.grid(padding=padding, expand=expand)
    table.style = PALETTE["fg"]
    return table


def themed_panel(
    message: RenderableType,
    *,
    border_color: str,
    text_style: str | None = None,
) -> Panel:
    """Return a Rich Panel styled with the shared palette."""
    return Panel.fit(
        message, border_style=border_color, style=text_style or PALETTE["fg"]
    )


def show_environment(report: EnvironmentReport) -> None:
    """Display environment checks in a formatted table."""
    table = themed_table(title="[accent]Environment[/accent]")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Details")
    for check in report.checks:
        status = "[ok]ok" if check.ok else "[error]missing"
        detail = _clean_detail(check.name, check.detail)
        table.add_row(check.name, status, detail)
    table.add_row(
        "gpu (nvidia)",
        "[ok]ok" if report.gpu_available else "[warn]not detected",
        _clean_detail("gpu (nvidia)", report.gpu_detail),
    )
    console.print(table)


def success_panel(message: str) -> None:
    """Display a success message with standard styling."""
    console.print(f"[ok]{message}[/]")


def info_panel(message: str) -> None:
    """Display an info message with standard styling."""
    console.print(f"[info]{message}[/]")


def confirm_action(message: str, *, default: bool = False) -> bool:
    """Show a Rich-styled confirmation prompt and return the user's choice."""
    prompt = message.strip() or "Proceed?"
    try:
        return Confirm.ask(
            f"[accent]?[/] {prompt}",
            default=default,
            show_default=True,
            console=console,
        )
    except KeyboardInterrupt:  # pragma: no cover - interactive guard
        console.print("[warn]Prompt cancelled by user.[/]")
        raise typer.Abort() from None
    except EOFError:  # pragma: no cover - interactive guard
        console.print("[warn]No input detected; cancelling.[/]")
        raise typer.Abort() from None


def _clean_detail(name: str, detail: str) -> str:
    """Reduce duplicated version lines by preferring lines matching the check name."""
    if not detail:
        return ""
    lines = [line.strip() for line in detail.splitlines() if line.strip()]
    if not lines:
        return ""
    if len(lines) == 1:
        return lines[0]
    normalized = name.lower().replace(" ", "")
    matching = [line for line in lines if normalized in line.lower().replace(" ", "")]
    selected = matching or lines
    return "\n".join(selected)
