from __future__ import annotations

import sys
import time as _time

import typer

from airpods import __description__
from airpods.logging import console
from airpods.runtime import ContainerRuntimeError

from .commands import register as register_commands
from .command_classes import AirpodsGroup
from .common import (
    DEFAULT_LOG_LINES,
    DEFAULT_PING_TIMEOUT,
    DEFAULT_STOP_TIMEOUT,
    ensure_podman_available,
    manager as _manager,
    print_version,
    resolve_services,
)
from .help import show_root_help
from .status_view import render_status

app = typer.Typer(
    name="airpods",
    help=__description__,
    context_settings={"help_option_names": []},
    rich_markup_mode="rich",
    cls=AirpodsGroup,
)

register_commands(app)


@app.callback(invoke_without_command=True)
def _root_command(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "-v",
        "--version",
        help="Show CLI version and exit.",
        is_eager=True,
    ),
    verbose: bool = typer.Option(
        False,
        "-V",
        "--verbose",
        help="Show detailed output and progress information.",
    ),
    help_: bool = typer.Option(
        False,
        "--help",
        "-h",
        help="Show this message and exit.",
        is_eager=True,
    ),
) -> None:
    # Store verbose flag in context for subcommands
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose

    if version:
        print_version()
        raise typer.Exit()
    if help_:
        show_root_help(ctx)
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        show_root_help(ctx)


def main() -> None:
    try:
        app()
    except ContainerRuntimeError as exc:
        console.print(f"[error]{exc}[/]")
        sys.exit(1)


# Backwards compatibility exports for legacy tests/importers.
manager = _manager
_resolve_services = resolve_services
_ensure_podman_available = ensure_podman_available
_render_status = render_status
time = _time

__all__ = [
    "app",
    "main",
    "DEFAULT_STOP_TIMEOUT",
    "DEFAULT_LOG_LINES",
    "DEFAULT_PING_TIMEOUT",
    "manager",
]
