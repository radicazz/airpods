from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import airpods.cli.help as cli_help
import airpods.cli.common as cli_common


def test_command_description_falls_back_to_docstring():
    """Ensure help descriptions derive from docstrings when explicit help is missing."""

    def sample():
        """Docstring first line.

        Additional detail ignored."""

    command = SimpleNamespace(help=None, short_help=None, callback=sample)
    assert cli_help._command_description(command) == "Docstring first line."


def test_help_never_probes_runtime(runner):
    from airpods.cli import app

    with patch.object(
        cli_common, "_apply_cli_config", side_effect=AssertionError("runtime probe")
    ):
        result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("status", "logs", "stop"):
        assert command in result.stdout
    assert "Unavailable" not in result.stdout
