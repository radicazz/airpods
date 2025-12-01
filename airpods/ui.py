"""UI utilities for rich console output."""

from __future__ import annotations

from collections import defaultdict
from typing import Mapping

from rich.panel import Panel
from rich.table import Table

from airpods.logging import console
from airpods.services import EnvironmentReport


def show_environment(report: EnvironmentReport) -> None:
    """Display environment checks in a formatted table."""
    table = Table(title="Environment", show_header=True, header_style="bold cyan")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Details")
    for check in report.checks:
        status = "[ok]ok" if check.ok else "[error]missing"
        table.add_row(check.name, status, check.detail)
    table.add_row("gpu (nvidia)", "[ok]ok" if report.gpu_available else "[warn]not detected", report.gpu_detail)
    console.print(table)


def success_panel(message: str) -> None:
    """Display a success message in a green panel."""
    console.print(Panel.fit(f"[ok]{message}[/]", border_style="green"))


def info_panel(message: str) -> None:
    """Display an info message in a cyan panel."""
    console.print(Panel.fit(f"[info]{message}[/]", border_style="cyan"))


def show_command_aliases(aliases: Mapping[str, str]) -> None:
    """Render command aliases aligned to the right of each command."""
    if not aliases:
        return
    grouped = defaultdict(list)
    for alias, command in aliases.items():
        grouped[command].append(alias)

    table = Table(title="Command aliases", header_style="bold magenta")
    table.add_column("Command", style="info")
    table.add_column("Alias", style="alias")
    for command in sorted(grouped):
        alias_text = ", ".join(f"[alias]{alias}[/]" for alias in sorted(grouped[command]))
        table.add_row(command, alias_text)
    console.print(table)
