"""Custom Typer/Click command classes for airpods CLI."""

from __future__ import annotations

import errno
import os
import sys
from typing import Any, Iterable, Optional, Sequence, TextIO, cast

import click
import typer
from typer import rich_utils
from typer.core import DEFAULT_MARKUP_MODE, MarkupMode, rich

from airpods.runtime import ContainerRuntimeError
from .commands.backup import BackupError, RestoreError
from airpods.configuration import ConfigurationError

from .common import HELP_OPTION_NAMES
from .help import render_usage_error, show_help_for_context


def _help_requested(args: Sequence[str]) -> bool:
    return any(flag in args for flag in HELP_OPTION_NAMES)


def _parameter_suggestions(
    ctx: click.Context,
    exc: click.MissingParameter,
) -> list[str]:
    param = exc.param
    if param is None:
        return []
    shell_complete = getattr(param, "shell_complete", None)
    if not callable(shell_complete):
        return []
    try:
        items = shell_complete(ctx, param, "")
    except Exception:
        return []
    suggestions = _normalize_completion_items(items)
    return sorted(set(suggestions))


def _normalize_completion_items(items: Iterable[Any]) -> list[str]:
    results: list[str] = []
    for item in items or []:
        value = getattr(item, "value", None)
        if value is None:
            value = str(item)
        if value:
            results.append(value)
    return results


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
                rv = self.invoke(ctx)
                if not standalone_mode:
                    return rv
                ctx.exit()
        except (
            ContainerRuntimeError,
            ConfigurationError,
            BackupError,
            RestoreError,
        ) as exc:
            from airpods.logging import console

            console.print(f"[error]{exc}[/]")
            if not standalone_mode:
                raise
            sys.exit(1)
        except (EOFError, KeyboardInterrupt) as exc:
            click.echo(file=sys.stderr)
            raise click.Abort() from exc
        except click.ClickException as exc:
            if not standalone_mode:
                raise

            # Custom error formatting that matches the airpods theme
            from airpods.logging import console

            if isinstance(exc, click.UsageError):
                help_ctx = exc.ctx or click.get_current_context(silent=True)

                if _help_requested(args):
                    if help_ctx is not None:
                        show_help_for_context(help_ctx)
                    sys.exit(0)

                command_name = (
                    help_ctx.command_path if help_ctx is not None else "airpods"
                )
                tip = f"Try '{command_name} --help' for more information."
                suggestions = None
                if isinstance(exc, click.MissingParameter) and help_ctx is not None:
                    suggestions = _parameter_suggestions(help_ctx, exc)

                render_usage_error(
                    help_ctx,
                    exc.format_message(),
                    suggestions=suggestions,
                    tip=tip,
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
