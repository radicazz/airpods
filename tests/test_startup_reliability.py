"""Regression coverage for startup reliability."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import typer

from airpods import config, launch
from airpods.cli import app
from airpods.cli.status_view import check_service_health, render_status
from airpods.services import ServiceSpec


def test_wait_timeout_returns_failure(monkeypatch):
    manager = MagicMock()
    manager.pod_status_rows.return_value = {}
    monkeypatch.setattr(launch.time, "monotonic", MagicMock(side_effect=[0, 11]))
    spec = ServiceSpec(
        name="example", pod="example", container="example-0", image="example/image"
    )
    cli = SimpleNamespace(
        startup_timeout=10, startup_check_interval=1, ping_timeout=0.1
    )
    with pytest.raises(typer.Exit) as failure:
        launch.perform_start(
            [spec],
            cli_config=cli,
            verbose=False,
            wait=True,
            force_cpu=False,
            yes=True,
            max_concurrent_pulls=1,
            manager=manager,
            gpu_available=False,
        )
    assert failure.value.exit_code == 1


def test_wait_checks_existing_services_without_relaunch(monkeypatch):
    manager = MagicMock()
    manager.pod_status_rows.return_value = {"example": {"Status": "Running"}}
    manager.service_ports.return_value = {}
    spec = ServiceSpec(
        name="example", pod="example", container="example-0", image="example/image"
    )
    cli = SimpleNamespace(
        startup_timeout=10, startup_check_interval=1, ping_timeout=0.1
    )
    monkeypatch.setattr(
        launch, "_maybe_install_custom_node_requirements", lambda *args, **kwargs: None
    )
    launch.perform_start(
        [],
        cli_config=cli,
        verbose=False,
        wait=True,
        force_cpu=False,
        yes=True,
        max_concurrent_pulls=1,
        manager=manager,
        gpu_available=False,
        already_running=[spec],
    )
    manager.start_service.assert_not_called()
    manager.pod_status_rows.assert_called_once()


@pytest.mark.parametrize("pre_fetch", [True, False])
def test_start_pulls_and_launches_same_cpu_image(runner, monkeypatch, pre_fetch):
    from airpods.cli.commands import start
    from airpods.configuration import get_config

    cfg = get_config().model_copy(deep=True)
    cfg.services["llamacpp"].command_args["model"] = "/custom/model.gguf"
    monkeypatch.setattr(start, "get_config", lambda: cfg)
    spec = ServiceSpec(
        name="llamacpp",
        pod="llamacpp",
        container="llamacpp-0",
        image="example/server-cuda",
        cpu_image="example/server",
        needs_gpu=True,
    )
    manager = MagicMock()
    manager.runtime.image_exists.return_value = False
    manager.pod_status_rows.return_value = {}
    manager.ensure_volumes.return_value = []
    monkeypatch.setattr(start, "manager", manager)
    monkeypatch.setattr(start, "resolve_services", lambda names: [spec])
    monkeypatch.setattr(start, "ensure_runtime_available", lambda: None)
    monkeypatch.setattr(start, "detect_gpu", lambda: (False, "no GPU"))
    monkeypatch.setattr(launch, "_maybe_sync_plugins", lambda *args, **kwargs: (0, 0))
    monkeypatch.setattr(
        launch, "_maybe_prepare_custom_nodes", lambda *args, **kwargs: ([], 0)
    )
    pulled = MagicMock()
    launched = MagicMock()
    monkeypatch.setattr(start._pull, "_pull_images_with_progress", pulled)
    monkeypatch.setattr(launch, "perform_start", launched)
    args = ["start", "llamacpp", "--yes"] + (["--pre-fetch"] if pre_fetch else [])
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.stdout
    selected = pulled.call_args[0][0]
    assert selected[0].image == "example/server"
    if pre_fetch:
        launched.assert_not_called()
    else:
        assert launched.call_args[0][0] == selected


def test_cpu_fallback_keeps_comfyui_provider_and_storage_consistent(monkeypatch):
    from airpods.configuration import get_config

    cfg = get_config().model_copy(deep=True)
    cfg.runtime.comfyui_provider = "mmartial"
    monkeypatch.setattr(config, "get_config", lambda: cfg)
    spec = config._service_spec_from_config("comfyui", cfg.services["comfyui"], cfg)
    basedir = next(mount.source for mount in spec.volumes if mount.target == "/basedir")
    effective = config.effective_service_specs(
        [spec], force_cpu=True, gpu_available=True, gpu_passthrough_ready=True
    )[0]
    assert effective.image.endswith(":cpu")
    assert effective.force_cpu
    assert effective.userns_mode is None
    assert "BASE_DIRECTORY" not in effective.env
    assert next(
        mount.source
        for mount in effective.volumes
        if mount.target == "/root/ComfyUI/models"
    ) == str(Path(basedir) / "models")
    assert (
        next(
            mount.source for mount in effective.volumes if mount.target == "/workspace"
        )
        == basedir
    )


def test_health_probe_closes_connection_when_request_fails(monkeypatch):
    connection = MagicMock()
    connection.request.side_effect = OSError("unavailable")
    monkeypatch.setattr(
        "airpods.cli.status_view.http.client.HTTPConnection",
        lambda *args, **kwargs: connection,
    )
    spec = ServiceSpec(
        name="example",
        pod="example",
        container="example-0",
        image="example/image",
        health_path="/health",
    )
    assert not check_service_health(spec, 8080)
    connection.close.assert_called_once()


def test_status_is_compact_and_preserves_crash_details(monkeypatch):
    manager = MagicMock()
    manager.pod_status_rows.return_value = {"example": {"Status": "Running"}}
    manager.runtime.container_inspect.return_value = {
        "State": {"Status": "exited", "ExitCode": 127}
    }
    manager.service_ports.return_value = {}
    console = MagicMock()
    monkeypatch.setattr("airpods.cli.status_view.manager", manager)
    monkeypatch.setattr("airpods.cli.status_view.console", console)
    spec = ServiceSpec(
        name="example", pod="example", container="example-0", image="example/image"
    )
    render_status([spec], show_legend=False)
    table = console.print.call_args[0][0]
    assert [column.header for column in table.columns] == ["Service", "Status", "Info"]
    assert "failed (exit 127)" in table.columns[1]._cells[0]
