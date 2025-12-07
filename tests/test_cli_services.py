from __future__ import annotations

from unittest.mock import patch

from airpods.cli import app


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


@patch("airpods.cli.commands.start.override_cli_config")
@patch("airpods.cli.commands.start.load_config")
@patch("airpods.cli.commands.start.ensure_podman_available")
@patch("airpods.cli.commands.start.manager")
def test_mode_overrides_default_dev(
    mock_manager, mock_ensure, mock_load_config, mock_override, runner
):
    """Default mode should be dev (gateway disabled)."""
    dummy_config = mock_load_config.return_value
    dummy_config.services = {
        "gateway": type("Svc", (), {"enabled": True})(),
        "open-webui": type("Svc", (), {"ports": [(3000, 8080)]})(),
        "ollama": type("Svc", (), {"ports": [(11434, 11434)]})(),
    }
    mock_manager.resolve.return_value = []
    mock_manager.ensure_network.return_value = False

    result = runner.invoke(app, ["start", "--init"])

    assert result.exit_code == 0
    mock_override.assert_called_once()
    applied_config = mock_override.call_args[0][0]
    assert applied_config.services["gateway"].enabled is False
    assert applied_config.services["open-webui"].ports == [(3000, 8080)]
    assert applied_config.services["ollama"].ports == [(11434, 11434)]


@patch("airpods.cli.commands.start.override_cli_config")
@patch("airpods.cli.commands.start.load_config")
@patch("airpods.cli.commands.start.ensure_podman_available")
@patch("airpods.cli.commands.start.manager")
def test_mode_overrides_prod_enables_gateway(
    mock_manager, mock_ensure, mock_load_config, mock_override, runner
):
    """Prod mode should enable gateway and hide open-webui/ollama ports."""
    dummy_config = mock_load_config.return_value
    dummy_config.services = {
        "gateway": type("Svc", (), {"enabled": False})(),
        "open-webui": type("Svc", (), {"ports": [(3000, 8080)]})(),
        "ollama": type("Svc", (), {"ports": [(11434, 11434)]})(),
    }
    mock_manager.resolve.return_value = []
    mock_manager.ensure_network.return_value = False

    result = runner.invoke(app, ["start", "prod", "--init"])

    assert result.exit_code == 0
    applied_config = mock_override.call_args[0][0]
    assert applied_config.services["gateway"].enabled is True
    assert applied_config.services["open-webui"].ports == []
    assert applied_config.services["ollama"].ports == []


@patch("airpods.cli.commands.start.override_cli_config")
@patch("airpods.cli.commands.start.load_config")
@patch("airpods.cli.commands.start.ensure_podman_available")
@patch("airpods.cli.commands.start.manager")
def test_mode_overrides_flags_take_priority(
    mock_manager, mock_ensure, mock_load_config, mock_override, runner
):
    """Explicit gateway flags should override mode defaults."""
    dummy_config = mock_load_config.return_value
    dummy_config.services = {
        "gateway": type("Svc", (), {"enabled": False})(),
        "open-webui": type("Svc", (), {"ports": [(3000, 8080)]})(),
        "ollama": type("Svc", (), {"ports": [(11434, 11434)]})(),
    }
    mock_manager.resolve.return_value = []
    mock_manager.ensure_network.return_value = False

    result = runner.invoke(app, ["start", "prod", "--no-gateway", "--init"])

    assert result.exit_code == 0
    applied_config = mock_override.call_args[0][0]
    assert applied_config.services["gateway"].enabled is False
    assert applied_config.services["open-webui"].ports == [(3000, 8080)]
    assert applied_config.services["ollama"].ports == [(11434, 11434)]
