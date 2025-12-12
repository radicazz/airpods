from __future__ import annotations

import os
from pathlib import Path

from airpods.cli import app
from airpods.configuration import reload_config
from airpods.configuration.loader import locate_config_file

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover
    import tomli as tomllib


def test_config_help_lists_subcommands(runner):
    """config --help enumerates subcommands without redundant hints."""
    result = runner.invoke(app, ["config", "--help"])

    assert result.exit_code == 0
    assert "Commands" in result.stdout
    assert "init" in result.stdout
    assert "show" in result.stdout
    assert "edit          --help" not in result.stdout


def test_config_init_creates_file(runner):
    home = Path(os.environ["AIRPODS_HOME"])
    result = runner.invoke(app, ["config", "init", "--force"])
    assert result.exit_code == 0
    assert (home / "configs" / "config.toml").exists()


def test_config_set_updates_value(runner):
    home = Path(os.environ["AIRPODS_HOME"])
    runner.invoke(app, ["config", "init", "--force"])
    locate_config_file.cache_clear()
    reload_config()
    result = runner.invoke(
        app, ["config", "set", "cli.stop_timeout", "45", "--type", "int"]
    )
    assert result.exit_code == 0
    data = tomllib.loads((home / "configs" / "config.toml").read_text())
    assert data["cli"]["stop_timeout"] == 45


def test_config_set_rejects_invalid_values(runner):
    home = Path(os.environ["AIRPODS_HOME"])
    runner.invoke(app, ["config", "init", "--force"])
    before = (home / "configs" / "config.toml").read_text()
    result = runner.invoke(
        app, ["config", "set", "cli.stop_timeout", "0", "--type", "int"]
    )
    assert result.exit_code != 0
    assert (home / "configs" / "config.toml").read_text() == before


def test_config_get_missing_key_shows_help(runner):
    result = runner.invoke(app, ["config", "get"])
    combined = result.stdout or ""
    assert result.exit_code != 0
    assert "Missing argument" in combined
    # Should suggest --help, not print full help
    assert "Try 'airpods config get --help' for more information" in combined
    assert "Print a specific configuration value" not in combined
