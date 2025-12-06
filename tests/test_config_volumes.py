from __future__ import annotations

import os
from pathlib import Path

import pytest

from airpods.configuration import get_config, reload_config
from airpods.configuration.errors import ConfigurationError
from airpods.configuration.loader import locate_config_file


def _fresh_spec(name: str):
    locate_config_file.cache_clear()
    reload_config()
    import airpods.config as config_module

    config = get_config()
    return config_module._service_spec_from_config(name, config.services[name], config)


def _assert_under_volumes(path: Path, home: Path) -> None:
    base = home / "volumes"
    assert Path(path).is_absolute()
    try:
        Path(path).resolve().relative_to(base.resolve())
    except ValueError:  # pragma: no cover - assertion helper
        pytest.fail(f"{path} is not inside {base}")


def test_comfyui_workspace_volume_binds_to_volumes_dir():
    home = Path(os.environ["AIRPODS_HOME"])
    spec = _fresh_spec("comfyui")
    workspace_mount = next(m for m in spec.volumes if m.target == "/workspace")
    assert workspace_mount.is_bind_mount
    _assert_under_volumes(Path(workspace_mount.source), home)


def test_comfyui_models_volume_binds_to_state_dir():
    home = Path(os.environ["AIRPODS_HOME"])
    spec = _fresh_spec("comfyui")
    models_mount = next(m for m in spec.volumes if m.target == "/root/ComfyUI/models")
    assert models_mount.is_bind_mount
    _assert_under_volumes(Path(models_mount.source), home)


def test_ollama_data_volume_binds_to_state_dir():
    home = Path(os.environ["AIRPODS_HOME"])
    spec = _fresh_spec("ollama")
    data_mount = next(m for m in spec.volumes if m.target == "/root/.ollama")
    assert data_mount.is_bind_mount
    _assert_under_volumes(Path(data_mount.source), home)


def test_open_webui_data_volume_binds_to_state_dir():
    home = Path(os.environ["AIRPODS_HOME"])
    spec = _fresh_spec("open-webui")
    data_mount = next(m for m in spec.volumes if m.target == "/app/backend/data")
    assert data_mount.is_bind_mount
    _assert_under_volumes(Path(data_mount.source), home)


def test_bind_prefix_rejects_directory_escape():
    import airpods.config as config_module

    with pytest.raises(ConfigurationError):
        config_module._resolve_volume_source("bind://../etc/passwd")
