"""Public command surface for standalone GGUF management."""

from unittest.mock import patch

import pytest

from airpods.cli import app


@pytest.mark.parametrize("args", [["gguf"], ["gguf", "--help"]])
def test_gguf_help_without_runtime(runner, args):
    with patch("airpods.cli.common.ensure_runtime_available") as runtime:
        result = runner.invoke(app, args)
    assert result.exit_code == 0
    for command in ("list", "pull", "remove", "search"):
        assert command in result.stdout
    runtime.assert_not_called()


@pytest.mark.parametrize("command", ["models", "model"])
def test_models_no_longer_contains_gguf_commands(runner, command):
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0
    assert "gguf" not in result.stdout.lower()
    assert "search" not in result.stdout.lower()
    assert runner.invoke(app, [command, "gguf", "list"]).exit_code != 0


def test_gguf_list_and_remove_without_ollama(runner, tmp_path):
    model = tmp_path / "example.gguf"
    model.write_bytes(b"test model")
    with (
        patch("airpods.cli.commands.gguf._gguf_dir", return_value=tmp_path),
        patch("airpods.ollama.ensure_ollama_available") as ollama,
    ):
        result = runner.invoke(app, ["gguf", "list"])
        assert result.exit_code == 0
        assert model.name in result.stdout
        result = runner.invoke(app, ["gguf", "remove", model.name])
        assert result.exit_code == 0
        assert not model.exists()
    ollama.assert_not_called()
