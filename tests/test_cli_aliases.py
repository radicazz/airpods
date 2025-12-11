from __future__ import annotations

from unittest.mock import patch

from airpods.cli import app


@patch("airpods.cli.commands.start.resolve_services")
@patch("airpods.cli.commands.start.ensure_podman_available")
@patch("airpods.cli.commands.start.manager")
@patch("airpods.cli.commands.start.detect_gpu")
def test_up_alias(mock_detect_gpu, mock_manager, mock_ensure, mock_resolve, runner):
    """'up' aliases start."""
    mock_detect_gpu.return_value = (False, "CPU")
    mock_resolve.return_value = []
    mock_ensure.return_value = None
    mock_manager.ensure_network.return_value = False
    mock_manager.ensure_volumes.return_value = []
    mock_manager.pull_images.return_value = None

    result = runner.invoke(app, ["up"])
    assert result.exit_code == 0


@patch("airpods.cli.commands.start.resolve_services")
@patch("airpods.cli.commands.start.ensure_podman_available")
@patch("airpods.cli.commands.start.manager")
@patch("airpods.cli.commands.start.detect_gpu")
def test_run_alias(mock_detect_gpu, mock_manager, mock_ensure, mock_resolve, runner):
    """'run' aliases start."""
    mock_detect_gpu.return_value = (False, "CPU")
    mock_resolve.return_value = []
    mock_ensure.return_value = None
    mock_manager.ensure_network.return_value = False
    mock_manager.ensure_volumes.return_value = []
    mock_manager.pull_images.return_value = None

    result = runner.invoke(app, ["run"])
    assert result.exit_code == 0


@patch("airpods.cli.commands.stop.resolve_services")
@patch("airpods.cli.commands.stop.ensure_podman_available")
@patch("airpods.cli.commands.stop.manager")
def test_down_alias(mock_manager, mock_ensure, mock_resolve, runner):
    """'down' aliases stop."""
    mock_resolve.return_value = []
    mock_ensure.return_value = None
    mock_manager.stop_service.return_value = True

    result = runner.invoke(app, ["down"])
    assert result.exit_code == 0


@patch("airpods.cli.commands.status.render_status")
@patch("airpods.cli.commands.status.ensure_podman_available")
@patch("airpods.cli.commands.status.resolve_services")
def test_ps_alias(mock_resolve, mock_ensure, mock_render, runner):
    """'ps' aliases status."""
    mock_resolve.return_value = []
    mock_ensure.return_value = None
    mock_render.return_value = None

    result = runner.invoke(app, ["ps"])
    assert result.exit_code == 0


@patch("airpods.cli.commands.status.render_status")
@patch("airpods.cli.commands.status.ensure_podman_available")
@patch("airpods.cli.commands.status.resolve_services")
def test_info_alias(mock_resolve, mock_ensure, mock_render, runner):
    """'info' aliases status."""
    mock_resolve.return_value = []
    mock_ensure.return_value = None
    mock_render.return_value = None

    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0
