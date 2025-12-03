from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from airpods.cli import app
from airpods.services import EnvironmentReport
from airpods.system import CheckResult


runner = CliRunner()


class TestCLIBasics:
    """Test basic CLI functionality."""

    def test_version_flag(self):
        """Test --version flag displays version."""
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "airpods" in result.stdout

    def test_help_flag(self):
        """Test --help flag displays help."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Commands" in result.stdout

    def test_version_command(self):
        """Test version command."""
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "airpods" in result.stdout


class TestCommandAliases:
    """Test that command aliases work correctly."""

    @patch("airpods.cli.commands.start.resolve_services")
    @patch("airpods.cli.commands.start.ensure_podman_available")
    @patch("airpods.cli.commands.start.manager")
    @patch("airpods.cli.commands.start.detect_gpu")
    def test_up_alias(self, mock_detect_gpu, mock_manager, mock_ensure, mock_resolve):
        """Test 'up' as alias for 'start'."""
        mock_detect_gpu.return_value = (False, "CPU")
        mock_resolve.return_value = []
        mock_ensure.return_value = None
        mock_manager.ensure_network.return_value = False
        mock_manager.ensure_volumes.return_value = []
        mock_manager.pull_images.return_value = None

        result = runner.invoke(app, ["up"])
        assert result.exit_code == 0

    @patch("airpods.cli.commands.stop.resolve_services")
    @patch("airpods.cli.commands.stop.ensure_podman_available")
    @patch("airpods.cli.commands.stop.manager")
    def test_down_alias(self, mock_manager, mock_ensure, mock_resolve):
        """Test 'down' as alias for 'stop'."""
        mock_resolve.return_value = []
        mock_ensure.return_value = None
        mock_manager.stop_service.return_value = True

        result = runner.invoke(app, ["down"])
        assert result.exit_code == 0

    @patch("airpods.cli.commands.status.render_status")
    @patch("airpods.cli.commands.status.ensure_podman_available")
    @patch("airpods.cli.commands.status.resolve_services")
    def test_ps_alias(self, mock_resolve, mock_ensure, mock_render):
        """Test 'ps' as alias for 'status'."""
        mock_resolve.return_value = []
        mock_ensure.return_value = None
        mock_render.return_value = None

        result = runner.invoke(app, ["ps"])
        assert result.exit_code == 0


class TestDoctorCommand:
    """Test the doctor command behavior."""

    @patch("airpods.cli.commands.doctor.ui.show_environment")
    @patch("airpods.cli.commands.doctor.manager")
    def test_doctor_success(self, mock_manager, mock_show_env):
        report = EnvironmentReport(checks=[], gpu_available=False, gpu_detail="n/a")
        mock_manager.report_environment.return_value = report

        result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 0
        assert "doctor complete" in result.stdout.lower()
        mock_show_env.assert_called_once_with(report)

    @patch("airpods.cli.commands.doctor.ui.show_environment")
    @patch("airpods.cli.commands.doctor.manager")
    def test_doctor_missing_dependency(self, mock_manager, mock_show_env):
        report = EnvironmentReport(
            checks=[CheckResult(name="podman", ok=False, detail="not found")],
            gpu_available=False,
            gpu_detail="n/a",
        )
        mock_manager.report_environment.return_value = report

        result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 1
        assert "missing dependencies" in result.stdout.lower()

    def test_doctor_help_uses_custom_renderer(self):
        result = runner.invoke(app, ["doctor", "--help"])

        assert result.exit_code == 0
        assert "Usage" in result.stdout
        assert "  airpods doctor [OPTIONS]" in result.stdout


class TestModernPrompts:
    """Test confirmation prompts use the modern UI helper."""

    @patch("airpods.cli.commands.start.ui.confirm_action")
    @patch("airpods.cli.commands.start.manager")
    @patch("airpods.cli.commands.start.resolve_services")
    @patch("airpods.cli.commands.start.ensure_podman_available")
    @patch("airpods.cli.commands.start.detect_gpu")
    def test_start_cancelled_when_confirmation_declined(
        self,
        mock_detect_gpu,
        mock_ensure,
        mock_resolve,
        mock_manager,
        mock_confirm,
    ):
        spec = MagicMock()
        spec.name = "ollama"
        spec.container = "ollama"
        spec.pod = "ollama"
        spec.image = "docker.io/ollama/ollama:latest"
        spec.volumes = []
        spec.ports = []
        mock_resolve.return_value = [spec]
        mock_detect_gpu.return_value = (False, "cpu")
        mock_ensure.return_value = None
        mock_manager.ensure_network.return_value = False
        mock_manager.ensure_volumes.return_value = []
        mock_manager.pull_images.return_value = None
        mock_manager.container_exists.return_value = True
        mock_confirm.return_value = False

        result = runner.invoke(app, ["start"])

        assert result.exit_code != 0
        assert "cancelled" in result.stdout.lower()
        mock_confirm.assert_called_once()
        mock_manager.start_service.assert_not_called()

    @patch("airpods.cli.commands.stop.ui.confirm_action")
    @patch("airpods.cli.commands.stop.manager")
    @patch("airpods.cli.commands.stop.resolve_services")
    @patch("airpods.cli.commands.stop.ensure_podman_available")
    def test_stop_remove_cancelled_when_confirmation_declined(
        self,
        mock_ensure,
        mock_resolve,
        mock_manager,
        mock_confirm,
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


class TestStatusCommand:
    """Test enhanced status command behavior."""

    @patch("airpods.cli.commands.status.render_status")
    @patch("airpods.cli.commands.status.ensure_podman_available")
    @patch("airpods.cli.commands.status.resolve_services")
    def test_status_watch_handles_interrupt(
        self, mock_resolve, mock_ensure, mock_render
    ):
        mock_resolve.return_value = [MagicMock()]
        mock_render.side_effect = [None]

        with patch(
            "airpods.cli.commands.status.time.sleep", side_effect=KeyboardInterrupt
        ):
            result = runner.invoke(app, ["status", "--watch", "0.1"])

        assert result.exit_code == 0
        mock_render.assert_called()

    @patch("airpods.cli.commands.status.ensure_podman_available")
    @patch("airpods.cli.commands.status.resolve_services")
    def test_status_invalid_watch_value(self, mock_resolve, mock_ensure):
        mock_resolve.return_value = []

        result = runner.invoke(app, ["status", "--watch", "0"])

        assert result.exit_code != 0
        assert "watch interval must be positive" in result.stdout.lower()


class TestServiceResolution:
    """Test service name resolution."""

    @patch("airpods.cli.commands.start.ensure_podman_available")
    @patch("airpods.cli.commands.start.manager")
    @patch("airpods.cli.common.manager")
    def test_unknown_service_error(
        self, mock_common_manager, mock_start_manager, mock_ensure
    ):
        """Test that unknown service names are rejected."""
        from airpods.services import UnknownServiceError

        mock_ensure.return_value = None
        mock_start_manager.ensure_network.return_value = False
        mock_common_manager.resolve.side_effect = UnknownServiceError("unknown")

        result = runner.invoke(app, ["start", "unknown"])
        assert result.exit_code != 0


class TestConstants:
    """Test that configuration constants are used."""

    def test_default_constants_defined(self):
        """Test that default constants are defined in module."""
        from airpods.cli import (
            DEFAULT_STOP_TIMEOUT,
            DEFAULT_LOG_LINES,
            DEFAULT_PING_TIMEOUT,
        )

        assert isinstance(DEFAULT_STOP_TIMEOUT, int)
        assert isinstance(DEFAULT_LOG_LINES, int)
        assert isinstance(DEFAULT_PING_TIMEOUT, float)
        assert DEFAULT_STOP_TIMEOUT > 0
        assert DEFAULT_LOG_LINES > 0
        assert DEFAULT_PING_TIMEOUT > 0
