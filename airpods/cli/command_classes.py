"""Custom Typer/Click command classes for airpods CLI."""

from __future__ import annotations

import errno
import os
import sys
from typing import Any, Optional, Sequence, TextIO, cast

import click
import typer
from typer import rich_utils
from typer.core import DEFAULT_MARKUP_MODE, MarkupMode, rich

from .help import show_help_for_context


def _airpods_main(
    self: click.Command,
    *,
    args: Optional[Sequence[str]] = None,
    prog_name: Optional[str] = None,
    complete_var: Optional[str] = None,
    standalone_mode: bool = True,
    windows_expand_args: bool = True,
    rich_markup_mode: MarkupMode = DEFAULT_MARKUP_MODE,
    **extra: Any,
) -> Any:
    """Typer-style main() with help suggestion on usage errors.

    This is based on typer.core._main, but when a click.UsageError is raised
    (typically missing required args/options), we suggest running --help
    instead of dumping the full help text.
    """

    if args is None:
        args = sys.argv[1:]
        if os.name == "nt" and windows_expand_args:  # pragma: no cover
            args = click.utils._expand_args(args)
    else:
        args = list(args)

    if prog_name is None:
        prog_name = click.utils._detect_program_name()

    self._main_shell_completion(extra, prog_name, complete_var)

    try:
        try:
            with self.make_context(prog_name, args, **extra) as ctx:
                # Check if the command being invoked requires a service that's not available
                from airpods.cli.help import COMMAND_DEPENDENCIES
                from airpods.cli.common import check_service_availability

                # Reconstruct the full command path (e.g., "models list")
                full_command_path = ctx.command_path
                if full_command_path in COMMAND_DEPENDENCIES:
                    service_name = COMMAND_DEPENDENCIES[full_command_path]
                    is_available, reason = check_service_availability(service_name)

                    if not is_available:
                        from airpods.logging import console

                        console.print(
                            f"[error]Error:[/] Command '{full_command_path}' is currently disabled."
                        )
                        console.print(
                            f"[info]{reason.capitalize()}. Start it with 'airpods start {service_name}'[/]"
                        )
                        sys.exit(1)

                rv = self.invoke(ctx)
                if not standalone_mode:
                    return rv
                ctx.exit()
        except (EOFError, KeyboardInterrupt) as exc:
            click.echo(file=sys.stderr)
            raise click.Abort() from exc
        except click.ClickException as exc:
            if not standalone_mode:
                raise

            # Custom error formatting that matches the airpods theme
            from airpods.logging import console

            if isinstance(exc, click.UsageError):
                # Show usage line and error message without the box
                help_ctx = exc.ctx or click.get_current_context(silent=True)
                if help_ctx is not None:
                    usage = help_ctx.command.get_usage(help_ctx)
                    console.print(f"[muted]{usage}[/]")

                console.print(f"[error]Error:[/] {exc.format_message()}")

                if help_ctx is not None:
                    # Suggest --help instead of printing the full help
                    command_name = help_ctx.command_path or "airpods"
                    console.print(
                        f"[info]Try '{command_name} --help' for more information.[/]"
                    )
            else:
                # For other Click exceptions, use default formatting
                if rich and rich_markup_mode is not None:
                    rich_utils.rich_format_error(exc)
                else:
                    exc.show()

            sys.exit(exc.exit_code)
        except OSError as exc:
            if exc.errno == errno.EPIPE:
                sys.stdout = cast(TextIO, click.utils.PacifyFlushWrapper(sys.stdout))
                sys.stderr = cast(TextIO, click.utils.PacifyFlushWrapper(sys.stderr))
                sys.exit(1)
            raise
    except click.exceptions.Exit as exc:
        if standalone_mode:
            sys.exit(exc.exit_code)
        return exc.exit_code
    except click.Abort:
        if not standalone_mode:
            raise
        if rich and rich_markup_mode is not None:
            rich_utils.rich_abort_error()
        else:
            click.echo("Aborted!", file=sys.stderr)
        sys.exit(1)


class AirpodsGroup(typer.core.TyperGroup):
    """Root group class that shows Rich help on invalid invocations."""

    def main(
        self,
        args: Optional[Sequence[str]] = None,
        prog_name: Optional[str] = None,
        complete_var: Optional[str] = None,
        standalone_mode: bool = True,
        windows_expand_args: bool = True,
        **extra: Any,
    ) -> Any:
        return _airpods_main(
            self,
            args=args,
            prog_name=prog_name,
            complete_var=complete_var,
            standalone_mode=standalone_mode,
            windows_expand_args=windows_expand_args,
            rich_markup_mode=self.rich_markup_mode,
            **extra,
        )
