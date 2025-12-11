from __future__ import annotations

from unittest.mock import ANY, patch

import pytest

from airpods.cli import app
from airpods.services import ServiceSpec


@patch("airpods.cli.commands.start.ensure_podman_available")
@patch("airpods.cli.commands.start.manager")
@patch("airpods.cli.common.manager")
def test_unknown_service_error(
    mock_common_manager, mock_start_manager, mock_ensure, runner
):
    """Unknown service names should surface Typer errors."""
    from airpods.services import UnknownServiceError

    mock_ensure.return_value = None
    mock_start_manager.ensure_network.return_value = False
    mock_common_manager.resolve.side_effect = UnknownServiceError("unknown")

    result = runner.invoke(app, ["start", "unknown"])
    assert result.exit_code != 0


def _make_mock_spec() -> ServiceSpec:
    return ServiceSpec(
        name="ollama",
        pod="pod",
        container="ollama-0",
        image="img",
        ports=[(11434, 11434)],
        health_path=None,
    )


def _mock_service_ready(mock_manager):
    mock_manager.pod_status_rows.side_effect = [
        {},
        {"pod": {"Status": "Running"}},
        {"pod": {"Status": "Running"}},
    ]
    mock_manager.container_exists.return_value = False
    mock_manager.service_ports.return_value = {"11434/tcp": [{"HostPort": "11434"}]}


@patch("airpods.cli.commands.start.manager")
@patch("airpods.cli.commands.start.get_cli_config")
@patch("airpods.cli.commands.start.ensure_podman_available")
@patch("airpods.cli.commands.start.resolve_services")
def test_start_respects_configured_concurrency(
    mock_resolve, mock_ensure, mock_get_cli_config, mock_manager, runner
):
    mock_resolve.return_value = [_make_mock_spec()]
    _mock_service_ready(mock_manager)
    mock_get_cli_config.return_value = type("Config", (), {"max_concurrent_pulls": 5})
    mock_manager.ensure_network.return_value = False
    mock_manager.ensure_volumes.return_value = []
    mock_manager.pull_images.return_value = None

    result = runner.invoke(app, ["start"])

    assert result.exit_code == 0
    mock_manager.pull_images.assert_any_call(
        mock_resolve.return_value,
        progress_callback=ANY,
        max_concurrent=5,
    )


@patch("airpods.cli.commands.start.manager")
@patch("airpods.cli.commands.start.get_cli_config")
@patch("airpods.cli.commands.start.ensure_podman_available")
@patch("airpods.cli.commands.start.resolve_services")
def test_start_sequential_flag_forces_single_pull(
    mock_resolve, mock_ensure, mock_get_cli_config, mock_manager, runner
):
    mock_resolve.return_value = [_make_mock_spec()]
    _mock_service_ready(mock_manager)
    mock_get_cli_config.return_value = type("Config", (), {"max_concurrent_pulls": 5})
    mock_manager.ensure_network.return_value = False
    mock_manager.ensure_volumes.return_value = []
    mock_manager.pull_images.return_value = None

    result = runner.invoke(app, ["start", "--sequential"])

    assert result.exit_code == 0
    mock_manager.pull_images.assert_any_call(
        mock_resolve.return_value,
        progress_callback=ANY,
        max_concurrent=1,
    )


@patch("airpods.cli.commands.start.manager")
@patch("airpods.cli.commands.start._pull_images_only")
@patch("airpods.cli.commands.start.get_cli_config")
@patch("airpods.cli.commands.start.ensure_podman_available")
@patch("airpods.cli.commands.start.resolve_services")
def test_pre_fetch_only_mode(
    mock_resolve, mock_ensure, mock_get_cli_config, mock_pull_only, mock_manager, runner
):
    spec = _make_mock_spec()
    mock_resolve.return_value = [spec]
    mock_ensure.return_value = None
    mock_get_cli_config.return_value = type("Config", (), {"max_concurrent_pulls": 3})

    result = runner.invoke(app, ["start", "--pre-fetch"])

    assert result.exit_code == 0
    mock_pull_only.assert_called_once_with([spec], max_concurrent=3)
    mock_manager.ensure_network.assert_not_called()
    mock_manager.ensure_volumes.assert_not_called()
