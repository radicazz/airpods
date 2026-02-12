from __future__ import annotations

from unittest.mock import patch

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


@patch("airpods.cli.commands.start.manager")
@patch("airpods.cli.commands.start._pull_images_with_progress")
@patch("airpods.cli.commands.start.get_cli_config")
@patch("airpods.cli.commands.start.ensure_podman_available")
@patch("airpods.cli.commands.start.resolve_services")
def test_start_respects_configured_concurrency(
    mock_resolve, mock_ensure, mock_get_cli_config, mock_pull, mock_manager, runner
):
    mock_resolve.return_value = [_make_mock_spec()]
    mock_get_cli_config.return_value = type(
        "Config",
        (),
        {
            "max_concurrent_pulls": 5,
            "startup_timeout": 10,
            "startup_check_interval": 0.01,
        },
    )
    mock_manager.ensure_network.return_value = False
    mock_manager.ensure_volumes.return_value = []
    mock_manager.pod_status_rows.return_value = {}
    mock_manager.container_exists.return_value = False

    result = runner.invoke(app, ["start"])

    assert result.exit_code == 0
    mock_pull.assert_called_once_with(
        mock_resolve.return_value, max_concurrent=5, verbose=False
    )


@patch("airpods.cli.commands.start.manager")
@patch("airpods.cli.commands.start._pull_images_with_progress")
@patch("airpods.cli.commands.start.get_cli_config")
@patch("airpods.cli.commands.start.ensure_podman_available")
@patch("airpods.cli.commands.start.resolve_services")
def test_start_sequential_flag_forces_single_pull(
    mock_resolve, mock_ensure, mock_get_cli_config, mock_pull, mock_manager, runner
):
    mock_resolve.return_value = [_make_mock_spec()]
    mock_get_cli_config.return_value = type(
        "Config",
        (),
        {
            "max_concurrent_pulls": 5,
            "startup_timeout": 10,
            "startup_check_interval": 0.01,
        },
    )
    mock_manager.ensure_network.return_value = False
    mock_manager.ensure_volumes.return_value = []
    mock_manager.pod_status_rows.return_value = {}
    mock_manager.container_exists.return_value = False

    result = runner.invoke(app, ["-V", "start", "--sequential"])

    assert result.exit_code == 0
    mock_pull.assert_called_once_with(
        mock_resolve.return_value, max_concurrent=1, verbose=True
    )


@patch("airpods.cli.commands.start.manager")
@patch("airpods.cli.commands.start._pull_images_with_progress")
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


@patch("airpods.cli.commands.start.manager")
@patch("airpods.cli.commands.start._pull_images_with_progress")
@patch("airpods.cli.commands.start.get_cli_config")
@patch("airpods.cli.commands.start.ensure_podman_available")
@patch("airpods.cli.commands.start.resolve_services")
def test_start_non_verbose_uses_pull_ui(
    mock_resolve, mock_ensure, mock_get_cli_config, mock_pull_only, mock_manager, runner
):
    spec = _make_mock_spec()
    mock_resolve.return_value = [spec]
    mock_get_cli_config.return_value = type(
        "Config",
        (),
        {
            "max_concurrent_pulls": 5,
            "startup_timeout": 10,
            "startup_check_interval": 0.01,
        },
    )
    mock_manager.ensure_network.return_value = False
    mock_manager.ensure_volumes.return_value = []
    mock_manager.pod_status_rows.return_value = {}
    mock_manager.container_exists.return_value = False

    result = runner.invoke(app, ["start"])

    assert result.exit_code == 0
    mock_pull_only.assert_called_once_with([spec], max_concurrent=5, verbose=False)


@patch("shutil.disk_usage")
@patch("rich.prompt.Confirm.ask")
@patch("airpods.cli.commands.start.manager")
@patch("airpods.cli.commands.start._pull_images_with_progress")
@patch("airpods.cli.commands.start.get_cli_config")
@patch("airpods.cli.commands.start.ensure_podman_available")
@patch("airpods.cli.commands.start.resolve_services")
def test_start_calls_runtime_get_remote_image_size(
    mock_resolve,
    mock_ensure,
    mock_get_cli_config,
    mock_pull,
    mock_manager,
    mock_confirm_ask,
    mock_disk_usage,
    runner,
):
    """Ensure start command can call runtime.get_remote_image_size without AttributeError.

    This test prevents regression where get_remote_image_size was incorrectly
    removed as "unused" when it's actually called via manager.runtime during
    the image download confirmation flow.
    """
    spec = _make_mock_spec()
    mock_resolve.return_value = [spec]
    mock_get_cli_config.return_value = type(
        "Config",
        (),
        {
            "max_concurrent_pulls": 3,
            "startup_timeout": 10,
            "startup_check_interval": 0.01,
        },
    )
    mock_manager.ensure_network.return_value = False
    mock_manager.ensure_volumes.return_value = []
    mock_manager.pod_status_rows.return_value = {}
    mock_manager.container_exists.return_value = False

    # Mock the runtime interface to have the required methods
    mock_manager.runtime.image_exists.return_value = False
    mock_manager.runtime.get_remote_image_size.return_value = 1024 * 1024 * 100  # 100MB

    # Mock disk usage
    from collections import namedtuple

    DiskUsage = namedtuple("DiskUsage", ["total", "used", "free"])
    mock_disk_usage.return_value = DiskUsage(
        total=1024 * 1024 * 1024 * 100,  # 100GB
        used=1024 * 1024 * 1024 * 50,  # 50GB
        free=1024 * 1024 * 1024 * 50,  # 50GB free
    )

    # User confirms download
    mock_confirm_ask.return_value = True

    result = runner.invoke(app, ["start"])

    assert result.exit_code == 0
    # Verify that get_remote_image_size was actually called
    assert mock_manager.runtime.get_remote_image_size.called


@patch("airpods.cli.commands.start._confirm_image_downloads")
@patch("airpods.cli.commands.start.manager")
@patch("airpods.cli.commands.start._pull_images_with_progress")
@patch("airpods.cli.commands.start.get_cli_config")
@patch("airpods.cli.commands.start.ensure_podman_available")
@patch("airpods.cli.commands.start.resolve_services")
def test_start_auto_confirm_from_config_skips_download_prompt(
    mock_resolve,
    mock_ensure,
    mock_get_cli_config,
    mock_pull,
    mock_manager,
    mock_confirm_downloads,
    runner,
):
    spec = _make_mock_spec()
    mock_resolve.return_value = [spec]
    mock_get_cli_config.return_value = type(
        "Config",
        (),
        {
            "max_concurrent_pulls": 3,
            "startup_timeout": 10,
            "startup_check_interval": 0.01,
            "auto_confirm": True,
        },
    )
    mock_manager.ensure_network.return_value = False
    mock_manager.ensure_volumes.return_value = []
    mock_manager.pod_status_rows.return_value = {}
    mock_manager.container_exists.return_value = False
    mock_manager.runtime.image_exists.return_value = False

    result = runner.invoke(app, ["start"])

    assert result.exit_code == 0
    mock_confirm_downloads.assert_not_called()
    mock_pull.assert_called_once_with([spec], max_concurrent=3, verbose=False)
