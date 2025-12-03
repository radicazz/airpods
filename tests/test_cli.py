from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover
    import tomli as tomllib

from airpods import state
from airpods.cli import app
import airpods.cli.completions as cli_completions
import airpods.cli.help as cli_help
from airpods.configuration import ConfigurationError, reload_config
from airpods.configuration.loader import locate_config_file
from airpods.services import EnvironmentReport
from airpods.system import CheckResult


runner = CliRunner()


def _completion_values(items):
    return [getattr(item, "value", item) for item in items]


@pytest.fixture(autouse=True)
def isolate_config(tmp_path, monkeypatch):
    """Force configuration artifacts into a temporary directory per test."""
    home = tmp_path / "airpods-home"
    monkeypatch.setenv("AIRPODS_HOME", str(home))
    state.state_root.cache_clear()
    locate_config_file.cache_clear()
    reload_config()
    yield


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

    def test_start_help_uses_custom_renderer(self):
        """Test start --help renders the Rich-powered help panel."""
        result = runner.invoke(app, ["start", "--help"])

        assert result.exit_code == 0
        assert "Usage" in result.stdout
        assert "airpods start" in result.stdout
        assert "Start pods for specified services" in result.stdout

    def test_config_help_lists_subcommands(self):
        """Config --help should enumerate its subcommands for quick discovery."""
        result = runner.invoke(app, ["config", "--help"])

        assert result.exit_code == 0
        assert "Commands" in result.stdout
        assert "init" in result.stdout
        assert "show" in result.stdout
        assert "edit          --help" not in result.stdout


class TestHelpRenderer:
    def test_command_description_falls_back_to_docstring(self):
        """Ensure help descriptions derive from docstrings when explicit help is missing."""

        def sample():
            """Docstring first line.

            Additional detail ignored."""

        command = SimpleNamespace(help=None, short_help=None, callback=sample)
        assert cli_help._command_description(command) == "Docstring first line."


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


class TestConfigCommand:
    """Tests for the configuration management command."""

    def test_config_init_creates_file(self):
        home = Path(os.environ["AIRPODS_HOME"])
        result = runner.invoke(app, ["config", "init", "--force"])
        assert result.exit_code == 0
        assert (home / "config.toml").exists()

    def test_config_set_updates_value(self):
        home = Path(os.environ["AIRPODS_HOME"])
        result = runner.invoke(
            app, ["config", "set", "cli.stop_timeout", "45", "--type", "int"]
        )
        assert result.exit_code == 0
        data = tomllib.loads((home / "config.toml").read_text())
        assert data["cli"]["stop_timeout"] == 45

    def test_config_set_rejects_invalid_values(self):
        home = Path(os.environ["AIRPODS_HOME"])
        runner.invoke(app, ["config", "init", "--force"])
        before = (home / "config.toml").read_text()
        result = runner.invoke(
            app, ["config", "set", "cli.stop_timeout", "0", "--type", "int"]
        )
        assert result.exit_code != 0
        assert (home / "config.toml").read_text() == before

    def test_config_root_help_option(self):
        result = runner.invoke(app, ["config", "--help"])

        assert result.exit_code == 0
        assert "airpods config" in result.stdout


class TestCompletionHelpers:
    """Tests for shell completion helper functions."""

    def test_service_completion_filters_candidates(self, monkeypatch):
        monkeypatch.setattr(
            cli_completions.manager.registry,
            "names",
            lambda: ["ollama", "open-webui", "comfyui"],
        )

        result = cli_completions.service_name_completion(None, None, "o")

        assert _completion_values(result) == ["ollama", "open-webui"]

    def test_config_key_completion_includes_nested_values(self, monkeypatch):
        class DummyConfig:
            def to_dict(self):
                return {
                    "cli": {"stop_timeout": 20},
                    "services": {
                        "ollama": {
                            "ports": [
                                {"host": 11434, "container": 11434},
                            ]
                        }
                    },
                }

        monkeypatch.setattr(cli_completions, "get_config", lambda: DummyConfig())

        cli_keys = _completion_values(
            cli_completions.config_key_completion(None, None, "cli.")
        )
        service_keys = _completion_values(
            cli_completions.config_key_completion(None, None, "services.oll")
        )

        assert "cli.stop_timeout" in cli_keys
        assert "services.ollama.ports.0.host" in service_keys

    def test_config_key_completion_handles_errors(self, monkeypatch):
        def _boom():
            raise ConfigurationError("broken")

        monkeypatch.setattr(cli_completions, "get_config", _boom)

        assert _completion_values(
            cli_completions.config_key_completion(None, None, "cli")
        ) == []
