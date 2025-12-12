from __future__ import annotations

from unittest.mock import MagicMock, patch

from airpods.cli import app


@patch("airpods.cli.commands.stop.ui.confirm_action")
@patch("airpods.cli.commands.stop.manager")
@patch("airpods.cli.commands.stop.resolve_services")
@patch("airpods.cli.commands.stop.ensure_podman_available")
def test_stop_remove_cancelled_when_confirmation_declined(
    mock_ensure,
    mock_resolve,
    mock_manager,
    mock_confirm,
    runner,
):
    spec = MagicMock()
    spec.name = "webui"
    spec.pod = "webui"
    spec.container = "webui"
    mock_resolve.return_value = [spec]
    mock_confirm.return_value = False

    result = runner.invoke(app, ["stop", "--remove"])

    assert result.exit_code != 0
    assert "cancelled" in result.stdout.lower()
    mock_confirm.assert_called_once()
    mock_manager.stop_service.assert_not_called()


@patch("airpods.cli.commands.stop.manager")
@patch("airpods.cli.commands.stop.resolve_services")
@patch("airpods.cli.commands.stop.ensure_podman_available")
def test_stop_reports_only_running_services(
    mock_ensure,
    mock_resolve,
    mock_manager,
    runner,
) -> None:
    spec_a = MagicMock()
    spec_a.name = "ollama"
    spec_a.pod = "ollama"
    spec_a.container = "ollama-0"
    spec_b = MagicMock()
    spec_b.name = "open-webui"
    spec_b.pod = "open-webui"
    spec_b.container = "open-webui-0"
    spec_c = MagicMock()
    spec_c.name = "comfyui"
    spec_c.pod = "comfyui"
    spec_c.container = "comfyui-0"

    mock_resolve.return_value = [spec_a, spec_b, spec_c]

    mock_manager.pod_status_rows.return_value = {
        "ollama": {"Name": "ollama", "Status": "Running"},
        "open-webui": {"Name": "open-webui", "Status": "Running"},
    }

    def fake_pod_exists(pod: str) -> bool:
        return pod in {"ollama", "open-webui"}

    mock_manager.runtime.pod_exists.side_effect = fake_pod_exists
    mock_manager.stop_service.return_value = True

    result = runner.invoke(app, ["stop"])

    assert result.exit_code == 0
    stdout = result.stdout
    assert "Stopping ollama" in stdout
    assert "Stopping open-webui" in stdout
    assert "Stopping comfyui" not in stdout
    assert "not found" in stdout.lower()
