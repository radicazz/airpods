"""Help text rendering and formatting for the CLI.

This module handles custom help display including:
- Root command help with examples
- Command table with alias mappings
- Option formatting
- Rich table rendering for beautiful terminal output
"""

from __future__ import annotations

import inspect
from typing import Iterable, Sequence

import click
import typer
from rich.console import Group
from rich.table import Table
from rich.text import Text

from airpods import __description__, ui
from airpods.logging import PALETTE, console

from .common import COMMAND_ALIASES, HELP_OPTION_NAMES


def command_help_option() -> bool:
    """Return the shared Typer option used to trigger command help."""

    return typer.Option(
        False,
        *HELP_OPTION_NAMES,
        help="Show this message and exit.",
        is_eager=True,
    )


def maybe_show_command_help(ctx: typer.Context, help_requested: bool) -> None:
    """Render the Rich-powered help view when a command receives --help."""

    if help_requested:
        show_command_help(ctx)
        raise typer.Exit()


def show_command_help(ctx: typer.Context) -> None:
    """Render help for an individual command using the shared Rich theme."""
    command = ctx.command
    if command is None:
        return

    renderables: list = []
    description = _command_description(command)
    if description:
        renderables.append(Text(description, style=PALETTE["fg"]))

    usage_text = Text(f"  {_format_usage_line(ctx)}", style=PALETTE["fg"])
    _append_section(renderables, "Usage", usage_text)

    command_rows = command_help_rows(ctx)
    if command_rows:
        _append_section(renderables, "Commands", build_command_table(ctx))

    argument_rows = argument_help_rows(ctx)
    if argument_rows:
        _append_section(renderables, "Arguments", build_argument_table(ctx))

    option_rows = option_help_rows(ctx)
    if option_rows:
        _append_section(renderables, "Options", build_option_table(ctx))

    _render_help_panel(renderables)


def _alias_groups() -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for alias, canonical in COMMAND_ALIASES.items():
        groups.setdefault(canonical, []).append(alias)
    for aliases in groups.values():
        aliases.sort()
    return groups


COMMAND_ALIAS_GROUPS = _alias_groups()


def show_root_help(ctx: typer.Context) -> None:
    renderables: list = [Text(__description__, style=PALETTE["fg"])]
    usage_text = Text("  airpods [OPTIONS] COMMAND [ARGS]...", style=PALETTE["fg"])
    _append_section(renderables, "Usage", usage_text)
    _append_section(renderables, "Commands", build_command_table(ctx))
    _append_section(renderables, "Options", build_option_table(ctx))
    _render_help_panel(renderables)


def build_help_table(
    ctx: typer.Context,
    rows: Iterable[tuple[str, ...]],
    *,
    column_styles: Sequence[dict[str, object]] | None = None,
) -> Table:
    table = ui.themed_grid(padding=(0, 3))
    styles = column_styles or (
        {"style": f"bold {PALETTE['green']}", "no_wrap": True},
        {"style": f"bold {PALETTE['purple']}", "no_wrap": True},
        {"style": PALETTE["fg"]},
    )
    for column in styles:
        table.add_column(**column)
    for row in rows:
        table.add_row(*row)
    return table


def build_command_table(ctx: typer.Context) -> Table:
    rows = command_help_rows(ctx)
    column_styles = (
        {"style": f"bold {PALETTE['green']}", "no_wrap": True},
        {"style": f"bold {PALETTE['purple']}", "no_wrap": True},
        {"style": f"bold {PALETTE['cyan']}", "no_wrap": True},
        {"style": PALETTE["fg"]},
    )
    return build_help_table(ctx, rows, column_styles=column_styles)


def build_option_table(ctx: typer.Context) -> Table:
    rows = option_help_rows(ctx)
    return build_help_table(ctx, rows)


def build_argument_table(ctx: typer.Context) -> Table:
    rows = argument_help_rows(ctx)
    column_styles = (
        {"style": f"bold {PALETTE['green']}", "no_wrap": True},
        {"style": PALETTE["fg"]},
    )
    return build_help_table(ctx, rows, column_styles=column_styles)


def command_help_rows(ctx: typer.Context):
    command_group = ctx.command
    if command_group is None or not isinstance(command_group, click.MultiCommand):
        return []
    rows = []
    for name in command_group.list_commands(ctx):
        command = command_group.get_command(ctx, name)
        if not command or command.hidden:
            continue
        alias_text = ", ".join(COMMAND_ALIAS_GROUPS.get(name, []))
        description = _command_description(command)
        option_hint = command_param_hint(command)
        rows.append((name, alias_text, option_hint, description))
    return rows


def option_help_rows(ctx: typer.Context):
    rows = []
    if ctx.command is None:
        return rows
    for param in ctx.command.params:
        if not isinstance(param, click.Option):
            continue
        name = primary_long_option(param)
        short_text = format_short_options(param)
        description = (param.help or "").strip()
        rows.append((name, short_text, description))
    return rows


def argument_help_rows(ctx: typer.Context):
    rows = []
    if ctx.command is None:
        return rows
    for param in ctx.command.params:
        if not isinstance(param, click.Argument):
            continue
        name = format_argument_hint(param)
        description = (getattr(param, "help", "") or "").strip()
        rows.append((name, description))
    return rows


def command_param_hint(command: click.Command) -> str:
    arguments = [param for param in command.params if isinstance(param, click.Argument)]
    if arguments:
        return format_argument_hint(arguments[0])
    options = [
        param
        for param in command.params
        if isinstance(param, click.Option) and not _is_help_option(param)
    ]
    if options:
        return primary_long_option(options[0]) or options[0].opts[0]
    return ""


def format_argument_hint(param: click.Argument) -> str:
    name = param.metavar or param.human_readable_name or param.name or ""
    if not name:
        return ""
    normalized = name.replace("_", " ").strip()
    normalized = normalized.replace(" ", "-").upper()
    return f"<{normalized}>"


def primary_long_option(param: "click.Option") -> str:
    for opt in param.opts:
        if opt.startswith("--"):
            return opt
    return param.opts[0] if param.opts else ""


def format_short_options(param: "click.Option") -> str:
    seen: list[str] = []
    for opt in list(param.opts) + list(param.secondary_opts):
        if not opt.startswith("-") or opt.startswith("--"):
            continue
        if opt not in seen:
            seen.append(opt)
    return ", ".join(seen)


def _format_usage_line(ctx: typer.Context) -> str:
    command = ctx.command
    if command is None:
        return _normalize_command_text(ctx.command_path)
    usage = command.get_usage(ctx).strip()
    if usage.lower().startswith("usage:"):
        usage = usage[6:].strip()
    return _normalize_command_text(usage)


def _normalize_command_text(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return "airpods"
    if text.startswith("-root-command"):
        remainder = text[len("-root-command") :].strip()
        text = f"airpods {remainder}".strip()
    elif " " not in text and text != "airpods":
        text = f"airpods {text}".strip()
    return text or "airpods"


def _append_section(renderables: list, title: str, body) -> None:
    if renderables:
        renderables.append(Text(""))
    renderables.append(Text(title, style="section"))
    renderables.append(body)


def _render_help_panel(renderables: list) -> None:
    if not renderables:
        return
    panel = ui.themed_panel(
        Group(*renderables),
        border_color=PALETTE["fg_muted"],
        text_style=PALETTE["fg"],
    )
    console.print(panel)


def _command_description(command: click.Command | None) -> str:
    if command is None:
        return ""
    text = (getattr(command, "help", None) or getattr(command, "short_help", None) or "").strip()
    if text:
        return text
    callback = getattr(command, "callback", None)
    if callback:
        doc = inspect.getdoc(callback) or ""
        if doc:
            return doc.splitlines()[0].strip()
    return ""


def _is_help_option(param: click.Option) -> bool:
    option_names = set(param.opts) | set(param.secondary_opts)
    return any(opt in option_names for opt in HELP_OPTION_NAMES)
