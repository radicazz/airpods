from __future__ import annotations

from copy import deepcopy

from airpods import state
from airpods.configuration import loader as loader_module
from airpods.configuration.errors import ConfigurationError
from airpods.configuration.resolver import _resolve_string, resolve_templates
import pytest
from pydantic import ValidationError

from airpods.configuration.schema import CLIConfig
from airpods.configuration.defaults import DEFAULT_CONFIG_DICT
from airpods.configuration.schema import AirpodsConfig


def test_locate_prefers_repo_over_xdg(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    repo_config = repo_root / "configs" / "config.toml"
    repo_config.parent.mkdir(parents=True)
    repo_config.write_text("repo", encoding="utf-8")

    xdg_home = tmp_path / "xdg"
    xdg_config = xdg_home / "airpods" / "configs" / "config.toml"
    xdg_config.parent.mkdir(parents=True)
    xdg_config.write_text("xdg", encoding="utf-8")

    monkeypatch.delenv("AIRPODS_HOME", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))

    loader_module.locate_config_file.cache_clear()
    state.clear_state_root_override()
    monkeypatch.setattr(loader_module, "detect_repo_root", lambda: repo_root)

    assert loader_module.locate_config_file() == repo_config.resolve()
    assert state.state_root() == repo_root.resolve()


def test_airpods_config_env_sets_state_root(tmp_path, monkeypatch):
    config_home = tmp_path / "custom_home"
    config_path = config_home / "configs" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("custom", encoding="utf-8")

    monkeypatch.setenv("AIRPODS_CONFIG", str(config_path))
    monkeypatch.delenv("AIRPODS_HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    loader_module.locate_config_file.cache_clear()
    state.clear_state_root_override()

    assert loader_module.locate_config_file() == config_path.resolve()
    assert state.state_root() == config_home.resolve()


def test_cli_config_max_concurrent_bounds():
    CLIConfig(max_concurrent_pulls=1)
    CLIConfig(max_concurrent_pulls=10)

    with pytest.raises(ValidationError):
        CLIConfig(max_concurrent_pulls=0)

    with pytest.raises(ValidationError):
        CLIConfig(max_concurrent_pulls=11)


def test_template_resolver_allows_repeated_references():
    context = {"runtime": {"host_gateway": "host.containers.internal"}}
    value = _resolve_string(
        "{{runtime.host_gateway}}/{{runtime.host_gateway}}",
        context,
        location="test",
    )
    assert value == "host.containers.internal/host.containers.internal"


def test_template_resolver_handles_mixed_runtime_and_service_refs():
    config_dict = deepcopy(DEFAULT_CONFIG_DICT)
    config_dict["runtime"]["host_gateway"] = "gateway.local"
    config_dict["services"]["open-webui"]["env"]["OLLAMA_BASE_URL"] = (
        "http://{{runtime.host_gateway}}:{{services.ollama.ports.0.host}}"
    )
    config_dict["services"]["ollama"]["env"]["PUBLIC_URL"] = (
        "http://localhost:{{services.open-webui.ports.0.host}}"
    )

    config = AirpodsConfig.from_dict(config_dict)
    resolved = resolve_templates(config)

    assert (
        resolved.services["open-webui"].env["OLLAMA_BASE_URL"]
        == "http://gateway.local:11434"
    )
    assert (
        resolved.services["ollama"].env["PUBLIC_URL"] == "http://localhost:3000"
    )
