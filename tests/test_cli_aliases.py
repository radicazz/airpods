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


@patch("airpods.cli.commands.doctor.manager")
@patch("airpods.cli.commands.doctor.detect_cuda_compute_capability")
@patch("airpods.cli.commands.doctor.gpu_utils.detect_nvidia_container_toolkit")
@patch("airpods.cli.commands.doctor.gpu_utils.check_cdi_available")
@patch("airpods.cli.commands.doctor.check_for_update")
def test_health_alias(
    mock_update, mock_cdi, mock_toolkit, mock_cuda, mock_manager, runner
):
    """'health' aliases doctor."""
    from airpods.services import EnvironmentReport
    from airpods.system import CheckResult

    mock_manager.report_environment.return_value = EnvironmentReport(
        checks=[CheckResult(name="podman", ok=True, detail="available")],
        gpu_available=False,
        gpu_detail="CPU",
    )
    mock_cuda.return_value = (False, None, None)
    mock_toolkit.return_value = (False, "not installed")
    mock_cdi.return_value = False
    mock_update.return_value = None

    result = runner.invoke(app, ["health"])
    assert result.exit_code == 0


@patch("airpods.cli.commands.models.ensure_ollama_running")
@patch("airpods.cli.commands.models.ollama.list_models")
def test_models_ls_alias(mock_list, mock_ensure, runner):
    """'models ls' aliases 'models list'."""
    mock_ensure.return_value = 11434
    mock_list.return_value = []

    result = runner.invoke(app, ["models", "ls"])
    assert result.exit_code == 0
    assert "No models installed" in result.output


@patch("airpods.cli.commands.models.ensure_ollama_running")
@patch("airpods.cli.commands.models.ollama.list_models")
def test_model_singular_alias(mock_list, mock_ensure, runner):
    """'model' aliases 'models'."""
    mock_ensure.return_value = 11434
    mock_list.return_value = []

    result = runner.invoke(app, ["model", "list"])
    assert result.exit_code == 0
    assert "No models installed" in result.output


@patch("airpods.cli.commands.models.ensure_ollama_running")
@patch("airpods.cli.commands.models.ollama.list_models")
@patch("airpods.cli.commands.models.ollama.delete_model")
def test_models_rm_alias(mock_delete, mock_list, mock_ensure, runner):
    """'models rm' aliases 'models remove'."""
    mock_ensure.return_value = 11434
    mock_list.return_value = [{"name": "llama3.2"}]

    result = runner.invoke(app, ["models", "rm", "llama3.2", "--force"])
    assert result.exit_code == 0
    mock_delete.assert_called_once_with("llama3.2", 11434)


@patch("airpods.cli.commands.workflows.comfyui_workflows_dir")
def test_workflows_ls_alias(mock_dir, runner, tmp_path):
    """'workflows ls' aliases 'workflows list'."""
    mock_dir.return_value = tmp_path
    (tmp_path / "test.json").write_text('{"nodes": []}')

    result = runner.invoke(app, ["workflows", "ls"])
    assert result.exit_code == 0


@patch("airpods.cli.commands.models._gguf_dir")
def test_gguf_ls_alias(mock_dir, runner, tmp_path):
    """'models gguf ls' aliases 'models gguf list'."""
    mock_dir.return_value = tmp_path
    # Create an empty directory
    tmp_path.mkdir(exist_ok=True)

    result = runner.invoke(app, ["models", "gguf", "ls"])
    assert result.exit_code == 0
    assert "No GGUF models found" in result.output
