"""Configuration management commands."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import MutableMapping
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Sequence

import tomlkit
import typer
from rich.syntax import Syntax

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover - Python <3.11
    import tomli as tomllib

from airpods import ui
from airpods.configuration import (
    ConfigurationError,
    get_config,
    locate_config_file,
    merge_configs,
    reload_config,
)
from airpods.configuration.defaults import DEFAULT_CONFIG_DICT
from airpods.configuration.schema import AirpodsConfig
from airpods.logging import console
from airpods.state import state_root

from ..common import COMMAND_CONTEXT
from ..completions import config_key_completion
from ..help import command_help_option, maybe_show_command_help, show_command_help
from ..type_defs import CommandMap


def register(app: typer.Typer) -> CommandMap:
    config_app = typer.Typer(help="Manage airpods configuration.", context_settings=COMMAND_CONTEXT)

    @config_app.callback(invoke_without_command=True)
    def _config_root(
        ctx: typer.Context,
        help_: bool = command_help_option(),
    ) -> None:
        """Entry point for the config command group."""

        maybe_show_command_help(ctx, help_)
        if ctx.invoked_subcommand is None:
            show_command_help(ctx)

    @config_app.command(context_settings=COMMAND_CONTEXT)
    def init(
        ctx: typer.Context,
        help_: bool = command_help_option(),
        force: bool = typer.Option(
            False, "--force", "-f", help="Overwrite existing config file."
        ),
    ) -> None:
        """Create a default configuration file."""
        maybe_show_command_help(ctx, help_)
        config_path = _default_config_path()
        if config_path.exists() and not force:
            console.print(f"[warn]Config file already exists: {config_path}[/]")
            console.print(
                "[info]Use --force to overwrite, or run 'airpods config edit'[/]"
            )
            raise typer.Exit(code=1)

        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(_generate_default_toml(), encoding="utf-8")
        console.print(f"[ok]Created config file: {config_path}[/]")

    @config_app.command(context_settings=COMMAND_CONTEXT)
    def show(
        ctx: typer.Context,
        help_: bool = command_help_option(),
        format: str = typer.Option(
            "toml",
            "--format",
            "-f",
            help="Output format (toml or json).",
        ),
    ) -> None:
        """Display the current configuration."""
        maybe_show_command_help(ctx, help_)
        try:
            config = get_config()
        except ConfigurationError as exc:
            console.print(f"[error]{exc}[/]")
            raise typer.Exit(code=1)

        format = format.lower()
        if format not in {"toml", "json"}:
            console.print(f"[error]Unsupported format: {format}[/]")
            raise typer.Exit(code=1)

        if format == "toml":
            config_path = locate_config_file()
            if config_path and config_path.exists():
                content = config_path.read_text()
            else:
                content = _generate_default_toml()
            syntax = Syntax(content, "toml", theme="monokai", line_numbers=True)
            console.print(syntax)
            return

        console.print_json(json.dumps(config.to_dict(), indent=2))

    @config_app.command(context_settings=COMMAND_CONTEXT)
    def path(
        ctx: typer.Context,
        help_: bool = command_help_option(),
    ) -> None:
        """Show configuration file location."""
        maybe_show_command_help(ctx, help_)
        config_path = locate_config_file()
        if config_path:
            console.print(f"[ok]Config file: {config_path}[/]")
            console.print(f"[info]Exists: {config_path.exists()}[/]")
        else:
            console.print("[warn]No config file found (using defaults)[/]")
            console.print(f"[info]Create one with: airpods config init[/]")
            console.print(f"[info]Default location: {_default_config_path()}[/]")

    @config_app.command(context_settings=COMMAND_CONTEXT)
    def edit(
        ctx: typer.Context,
        help_: bool = command_help_option(),
    ) -> None:
        """Open configuration file in $EDITOR."""
        maybe_show_command_help(ctx, help_)
        config_path = locate_config_file()
        if not config_path:
            console.print("[warn]No config file exists yet[/]")
            if not ui.confirm_action("Create default config file now?"):
                raise typer.Exit(code=1)
            config_path = _default_config_path()
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(_generate_default_toml(), encoding="utf-8")

        editor = os.environ.get("EDITOR", "nano")
        try:
            subprocess.run([editor, str(config_path)], check=True)
            console.print("[ok]Config updated[/]")
            console.print("[info]Changes will apply on the next command invocation.[/]")
        except subprocess.CalledProcessError:
            console.print(f"[error]Failed to run editor: {editor}[/]")
            raise typer.Exit(code=1)
        except FileNotFoundError:
            console.print(f"[error]Editor not found: {editor}[/]")
            raise typer.Exit(code=1)

    @config_app.command(context_settings=COMMAND_CONTEXT)
    def validate(
        ctx: typer.Context,
        help_: bool = command_help_option(),
    ) -> None:
        """Validate the configuration file."""
        maybe_show_command_help(ctx, help_)
        try:
            config = reload_config()
        except ConfigurationError as exc:
            console.print(f"[error]Configuration is invalid:[/]")
            console.print(f"[error]{exc}[/]")
            raise typer.Exit(code=1)

        console.print("[ok]Configuration is valid[/]")
        _check_config_warnings(config)

    @config_app.command(context_settings=COMMAND_CONTEXT)
    def reset(
        ctx: typer.Context,
        help_: bool = command_help_option(),
        force: bool = typer.Option(
            False, "--force", "-f", help="Skip confirmation prompt."
        ),
    ) -> None:
        """Reset configuration to defaults."""
        maybe_show_command_help(ctx, help_)
        config_path = locate_config_file()
        if not config_path:
            console.print("[warn]No config file to reset[/]")
            raise typer.Exit()

        if not force:
            if not ui.confirm_action(
                f"Reset {config_path} to defaults? This cannot be undone.",
                default=False,
            ):
                console.print("[info]Reset cancelled[/]")
                raise typer.Exit(code=0)

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = config_path.with_name(f"{config_path.name}.{timestamp}.bak")
        counter = 1
        while backup_path.exists():
            backup_path = config_path.with_name(
                f"{config_path.name}.{timestamp}.{counter}.bak"
            )
            counter += 1
        shutil.copy2(config_path, backup_path)
        console.print(f"[info]Backed up old config to: {backup_path}[/]")

        config_path.write_text(_generate_default_toml(), encoding="utf-8")
        console.print(f"[ok]Reset config to defaults: {config_path}[/]")

    @config_app.command(context_settings=COMMAND_CONTEXT)
    def get(
        ctx: typer.Context,
        help_: bool = command_help_option(),
        key: str = typer.Argument(
            ...,
            help="Config key in dot notation",
            shell_complete=config_key_completion,
        ),
    ) -> None:
        """Print a specific configuration value."""
        maybe_show_command_help(ctx, help_)
        try:
            config = get_config()
        except ConfigurationError as exc:
            console.print(f"[error]{exc}[/]")
            raise typer.Exit(code=1)
        value = _get_nested_value(config.to_dict(), key)
        if value is None:
            console.print(f"[warn]Key not found: {key}[/]")
            raise typer.Exit(code=1)
        console.print(f"[ok]{key} = {value}[/]")

    @config_app.command(context_settings=COMMAND_CONTEXT)
    def set(
        ctx: typer.Context,
        help_: bool = command_help_option(),
        key: str = typer.Argument(
            ...,
            help="Config key in dot notation",
            shell_complete=config_key_completion,
        ),
        value: str = typer.Argument(..., help="New value"),
        value_type: str = typer.Option(
            "auto",
            "--type",
            "-t",
            help="Interpret VALUE using this type before validation.",
        ),
    ) -> None:
        """Update a specific configuration value."""
        maybe_show_command_help(ctx, help_)
        config_path, created = _ensure_config_file()
        if created:
            console.print(f"[info]Created config file at {config_path}[/]")

        try:
            document = tomlkit.parse(config_path.read_text(encoding="utf-8"))
        except (OSError, tomlkit.exceptions.ParseError) as exc:
            console.print(f"[error]Cannot read config: {exc}[/]")
            raise typer.Exit(code=1)

        value_type_normalized = value_type.lower()
        if value_type_normalized not in {"auto", "str", "int", "float", "bool", "json"}:
            console.print(f"[error]Unsupported type: {value_type}[/]")
            raise typer.Exit(code=1)

        try:
            coerced = _coerce_value(value, value_type_normalized)  # type: ignore[arg-type]
        except ValueError as exc:
            console.print(f"[error]{exc}[/]")
            raise typer.Exit(code=1)

        try:
            _set_nested_value(document, key.split("."), coerced)
        except ValueError as exc:
            console.print(f"[error]{exc}[/]")
            raise typer.Exit(code=1)

        candidate = tomllib.loads(tomlkit.dumps(document))
        merged = merge_configs(DEFAULT_CONFIG_DICT, candidate)
        try:
            AirpodsConfig.from_dict(merged)
        except Exception as exc:
            console.print(f"[error]Invalid value for {key}: {exc}[/]")
            console.print("[info]No changes were saved.[/]")
            raise typer.Exit(code=1)

        config_path.write_text(tomlkit.dumps(document), encoding="utf-8")
        reload_config()
        console.print(f"[ok]Updated {key} in {config_path}[/]")

    app.add_typer(config_app, name="config")

    return {
        "config": config_app,
        "config:init": init,
        "config:show": show,
        "config:path": path,
        "config:edit": edit,
        "config:validate": validate,
        "config:reset": reset,
        "config:get": get,
        "config:set": set,
    }


def _default_config_path() -> Path:
    return state_root() / "config.toml"


def _generate_default_toml() -> str:
    document = tomlkit.document()
    document.update(DEFAULT_CONFIG_DICT)
    return tomlkit.dumps(document)


def _get_nested_value(data: dict, path: str) -> Any:
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _ensure_config_file() -> tuple[Path, bool]:
    path = locate_config_file() or _default_config_path()
    if path.exists():
        return path, False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_generate_default_toml(), encoding="utf-8")
    return path, True


def _set_nested_value(
    document: MutableMapping[str, Any], dotted: Sequence[str], value: Any
) -> None:
    if not dotted or any(part == "" for part in dotted):
        raise ValueError("Key path cannot be empty")

    current = document
    for part in dotted[:-1]:
        if part not in current or not isinstance(current[part], MutableMapping):
            current[part] = tomlkit.table()
        current = current[part]

    current[dotted[-1]] = tomlkit.item(value)


def _coerce_value(
    raw: str, kind: Literal["auto", "str", "int", "float", "bool", "json"]
) -> Any:
    if kind == "auto":
        for candidate in ("bool", "int", "float", "json"):
            try:
                return _coerce_value(raw, candidate)  # type: ignore[arg-type]
            except ValueError:
                continue
        return raw
    if kind == "str":
        return raw
    if kind == "bool":
        normalized = raw.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
        raise ValueError(f"Cannot parse boolean value from '{raw}'")
    if kind == "int":
        try:
            return int(raw, 10)
        except ValueError as exc:
            raise ValueError(f"Cannot parse integer value from '{raw}'") from exc
    if kind == "float":
        try:
            return float(raw)
        except ValueError as exc:
            raise ValueError(f"Cannot parse float value from '{raw}'") from exc
    if kind == "json":
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Cannot parse JSON value from '{raw}': {exc}") from exc
    raise ValueError(f"Unsupported type: {kind}")


def _check_config_warnings(config) -> None:
    warnings: list[str] = []

    used_ports: dict[int, list[str]] = {}
    for service_name, service in config.services.items():
        if not service.enabled:
            continue
        if not service.ports:
            continue
        for port_mapping in service.ports:
            host_port = port_mapping.host
            if host_port in used_ports:
                for existing_service in used_ports[host_port]:
                    warnings.append(
                        f"Port conflict: {service_name} and {existing_service} use host port {host_port}"
                    )
                used_ports[host_port].append(service_name)
            else:
                used_ports[host_port] = [service_name]
        if service.image.endswith(":latest"):
            warnings.append(
                f"{service_name}: using ':latest' image tag (consider pinning the version)"
            )

    if warnings:
        console.print("\n[warn]Warnings:[/]")
        for warning in warnings:
            console.print(f"  [warn]⚠[/warn]  {warning}")
