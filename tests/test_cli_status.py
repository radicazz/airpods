from __future__ import annotations

from unittest.mock import MagicMock, patch

from airpods.cli import app


@patch("airpods.cli.commands.status.render_status")
@patch("airpods.cli.commands.status.ensure_podman_available")
@patch("airpods.cli.commands.status.resolve_services")
def test_status_watch_handles_interrupt(mock_resolve, mock_ensure, mock_render, runner):
    mock_resolve.return_value = [MagicMock()]
    mock_render.side_effect = [None]

    with patch("airpods.cli.commands.status.time.sleep", side_effect=KeyboardInterrupt):
        result = runner.invoke(app, ["status", "--watch", "0.1"])

    assert result.exit_code == 0
    mock_render.assert_called()


@patch("airpods.cli.commands.status.ensure_podman_available")
@patch("airpods.cli.commands.status.resolve_services")
def test_status_invalid_watch_value(mock_resolve, mock_ensure, runner):
    mock_resolve.return_value = []

    result = runner.invoke(app, ["status", "--watch", "0"])

    assert result.exit_code != 0
    assert "watch interval must be positive" in result.stdout.lower()
