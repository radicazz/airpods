"""Tests for the clean command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from airpods.cli import app

runner = CliRunner()


@pytest.fixture
def mock_manager():
    """Mock the service manager for clean tests."""
    with patch("airpods.cli.commands.clean.manager") as mock:
        mock.runtime.pod_exists.return_value = False
        mock.runtime.list_volumes.return_value = []
        mock.runtime.image_size.return_value = None
        mock.runtime.network_exists.return_value = False
        mock.network_name = "airpods_network"
        yield mock


@pytest.fixture
def mock_resolve_services():
    """Mock resolve_services to return test specs."""
    with patch("airpods.cli.commands.clean.resolve_services") as mock:
        spec1 = MagicMock()
        spec1.name = "ollama"
        spec1.pod = "ollama_pod"
        spec1.image = "docker.io/ollama/ollama:latest"

        spec2 = MagicMock()
        spec2.name = "webui"
        spec2.pod = "webui_pod"
        spec2.image = "ghcr.io/open-webui/open-webui:latest"

        mock.return_value = [spec1, spec2]
        yield mock


@pytest.fixture
def mock_podman():
    """Mock podman availability check."""
    with patch("airpods.cli.commands.clean.ensure_podman_available"):
        yield


@pytest.fixture
def mock_dirs(tmp_path):
    """Mock state directories."""
    volumes = tmp_path / "volumes"
    configs = tmp_path / "configs"
    volumes.mkdir()
    configs.mkdir()

    with (
        patch("airpods.cli.commands.clean.volumes_dir", return_value=volumes),
        patch("airpods.cli.commands.clean.configs_dir", return_value=configs),
    ):
        yield {"volumes": volumes, "configs": configs}


def test_clean_no_options_shows_help(mock_podman):
    """Test that clean with no options shows error and suggests --help."""
    result = runner.invoke(app, ["clean"])
    assert result.exit_code == 1
    assert "No cleanup targets specified" in result.stdout
    assert "Try 'airpods clean --help' for more information" in result.stdout
    # Should NOT show full help text
    assert "Remove volumes, images, configs, and user data" not in result.stdout


def test_clean_help_shows_usage():
    """Test that clean --help shows proper usage."""
    result = runner.invoke(app, ["clean", "--help"])
    assert result.exit_code == 0
    assert "Remove volumes, images, configs, and user data" in result.stdout
    assert "--all" in result.stdout
    assert "--pods" in result.stdout
    assert "--volumes" in result.stdout
    assert "--images" in result.stdout
    assert "--network" in result.stdout
    assert "--configs" in result.stdout
    assert "--dry-run" in result.stdout


def test_clean_dry_run_shows_plan(
    mock_manager, mock_resolve_services, mock_podman, mock_dirs
):
    """Test that dry-run mode shows what would be deleted."""
    mock_manager.runtime.pod_exists.return_value = True
    mock_manager.runtime.list_volumes.return_value = ["airpods_ollama_data"]
    mock_manager.runtime.image_size.return_value = "3.5GB"
    mock_manager.runtime.network_exists.return_value = True

    result = runner.invoke(app, ["clean", "--all", "--dry-run"])
    assert result.exit_code == 0
    assert "DRY RUN" in result.stdout
    assert "ollama" in result.stdout
    assert "airpods_ollama_data" in result.stdout
    assert "airpods_network" in result.stdout
    assert "No changes were made" in result.stdout


def test_clean_nothing_to_clean(mock_manager, mock_resolve_services, mock_podman):
    """Test clean when there's nothing to clean."""
    result = runner.invoke(app, ["clean", "--all", "--force"])
    assert result.exit_code == 0
    assert "Nothing to clean" in result.stdout


def test_clean_pods_only(mock_manager, mock_resolve_services, mock_podman):
    """Test cleaning only pods."""
    mock_manager.runtime.pod_exists.return_value = True

    result = runner.invoke(app, ["clean", "--pods", "--force"])
    assert result.exit_code == 0
    assert "Cleaning pods" in result.stdout
    mock_manager.runtime.stop_pod.assert_called()
    mock_manager.runtime.remove_pod.assert_called()


def test_clean_volumes_only(
    mock_manager, mock_resolve_services, mock_podman, mock_dirs
):
    """Test cleaning only volumes."""
    mock_manager.runtime.list_volumes.return_value = [
        "airpods_ollama_data",
        "airpods_webui_data",
    ]

    # Create bind mount directories
    volumes_dir = mock_dirs["volumes"]
    (volumes_dir / "airpods_ollama_data").mkdir()
    (volumes_dir / "comfyui").mkdir()
    (volumes_dir / "comfyui" / "workspace").mkdir()
    plugin_dir = volumes_dir / "webui_plugins"
    plugin_dir.mkdir()

    result = runner.invoke(app, ["clean", "--volumes", "--force"])
    assert result.exit_code == 0
    assert "Cleaning volumes" in result.stdout
    assert mock_manager.runtime.remove_volume.call_count == 2
    assert not plugin_dir.exists()


def test_clean_images_only(mock_manager, mock_resolve_services, mock_podman):
    """Test cleaning only images."""
    mock_manager.runtime.image_size.return_value = "3.5GB"

    result = runner.invoke(app, ["clean", "--images", "--force"])
    assert result.exit_code == 0
    assert "Cleaning images" in result.stdout
    assert mock_manager.runtime.remove_image.call_count == 2


def test_clean_network_only(mock_manager, mock_resolve_services, mock_podman):
    """Test cleaning only network."""
    mock_manager.runtime.network_exists.return_value = True

    result = runner.invoke(app, ["clean", "--network", "--force"])
    assert result.exit_code == 0
    assert "Cleaning network" in result.stdout
    mock_manager.runtime.remove_network.assert_called_with("airpods_network")


def test_clean_configs_only(
    mock_manager, mock_resolve_services, mock_podman, mock_dirs
):
    """Test cleaning only config files."""
    configs_dir = mock_dirs["configs"]
    config_file = configs_dir / "config.toml"
    secret_file = configs_dir / "webui_secret"
    config_file.write_text("test config")
    secret_file.write_text("secret")

    result = runner.invoke(app, ["clean", "--configs", "--force"])
    assert result.exit_code == 0
    assert "Cleaning configs" in result.stdout
    assert not config_file.exists()
    assert not secret_file.exists()


def test_clean_configs_with_backup(
    mock_manager, mock_resolve_services, mock_podman, mock_dirs
):
    """Test that config.toml is backed up before deletion."""
    configs_dir = mock_dirs["configs"]
    config_file = configs_dir / "config.toml"
    config_file.write_text("test config")

    result = runner.invoke(app, ["clean", "--configs", "--force", "--backup-config"])
    assert result.exit_code == 0
    assert "Backed up config" in result.stdout
    assert not config_file.exists()
    # Check that a backup file was created
    backups = list(configs_dir.glob("config.toml.backup.*"))
    assert len(backups) == 1


def test_clean_configs_without_backup(
    mock_manager, mock_resolve_services, mock_podman, mock_dirs
):
    """Test that config.toml can be deleted without backup."""
    configs_dir = mock_dirs["configs"]
    config_file = configs_dir / "config.toml"
    config_file.write_text("test config")

    result = runner.invoke(app, ["clean", "--configs", "--force", "--no-backup-config"])
    assert result.exit_code == 0
    assert not config_file.exists()
    # Check that no backup file was created
    backups = list(configs_dir.glob("config.toml.backup.*"))
    assert len(backups) == 0


@patch("airpods.cli.commands.clean.ui.confirm_action")
def test_clean_requires_confirmation_without_force(
    mock_confirm, mock_manager, mock_resolve_services, mock_podman
):
    """Test that clean requires confirmation when --force is not used."""
    mock_manager.runtime.pod_exists.return_value = True
    mock_confirm.return_value = True

    result = runner.invoke(app, ["clean", "--pods"])
    assert result.exit_code == 0
    mock_confirm.assert_called_once()


@patch("airpods.cli.commands.clean.ui.confirm_action")
def test_clean_cancelled_by_user(
    mock_confirm, mock_manager, mock_resolve_services, mock_podman
):
    """Test that clean can be cancelled by the user."""
    mock_manager.runtime.pod_exists.return_value = True
    mock_confirm.return_value = False

    result = runner.invoke(app, ["clean", "--pods"])
    assert result.exit_code == 1
    assert "Cleanup cancelled" in result.stdout


def test_clean_all_flag(mock_manager, mock_resolve_services, mock_podman, mock_dirs):
    """Test that --all flag enables all cleanup targets."""
    mock_manager.runtime.pod_exists.return_value = True
    mock_manager.runtime.list_volumes.return_value = ["airpods_ollama_data"]
    mock_manager.runtime.image_size.return_value = "3.5GB"
    mock_manager.runtime.network_exists.return_value = True

    configs_dir = mock_dirs["configs"]
    (configs_dir / "config.toml").write_text("test")

    result = runner.invoke(app, ["clean", "--all", "--force"])
    assert result.exit_code == 0
    assert "Cleaning pods" in result.stdout
    assert "Cleaning volumes" in result.stdout
    assert "Cleaning images" in result.stdout
    assert "Cleaning network" in result.stdout
    assert "Cleaning configs" in result.stdout
    assert "Cleanup complete" in result.stdout


def test_clean_handles_podman_errors(mock_manager, mock_resolve_services, mock_podman):
    """Test that clean handles podman errors gracefully."""
    from airpods.runtime import ContainerRuntimeError

    mock_manager.runtime.pod_exists.return_value = True
    mock_manager.runtime.stop_pod.side_effect = ContainerRuntimeError("Test error")

    result = runner.invoke(app, ["clean", "--pods", "--force"])
    assert result.exit_code == 0
    assert "Failed to remove" in result.stdout


def test_clean_handles_filesystem_errors(
    mock_manager, mock_resolve_services, mock_podman, mock_dirs
):
    """Test that clean handles filesystem errors gracefully."""
    configs_dir = mock_dirs["configs"]
    config_file = configs_dir / "config.toml"
    config_file.write_text("test")

    with patch("pathlib.Path.unlink", side_effect=OSError("Test error")):
        result = runner.invoke(app, ["clean", "--configs", "--force"])
        assert result.exit_code == 0
        assert "Failed to remove" in result.stdout
