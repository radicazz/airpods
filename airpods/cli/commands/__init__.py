from __future__ import annotations

import typer

from . import backup, clean, config, doctor, logs, models, start, status, stop, version
from ..common import ALIAS_HELP_TEMPLATE, COMMAND_ALIASES, COMMAND_CONTEXT
from ..type_defs import CommandMap

COMMAND_MODULES = [
    version,
    doctor,
    start,
    stop,
    status,
    logs,
    models,
    config,
    clean,
    backup,
]


def register(app: typer.Typer) -> None:
    """Attach all CLI subcommands and their aliases to the shared Typer app."""
    command_map: CommandMap = {}
    for module in COMMAND_MODULES:
        command_map.update(module.register(app))

    for alias, canonical in COMMAND_ALIASES.items():
        handler = command_map.get(canonical)
        if handler is None:
            raise ValueError(
                f"Alias '{alias}' points to unknown command '{canonical}'. "
                f"Available commands: {', '.join(sorted(command_map.keys()))}"
            )
        app.command(
            name=alias,
            help=ALIAS_HELP_TEMPLATE.format(canonical=canonical),
            hidden=True,
            context_settings=COMMAND_CONTEXT,
        )(handler)
