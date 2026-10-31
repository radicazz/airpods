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


def test_open_webui_no_ollama_by_default():
    """Test that Open WebUI doesn't have Ollama env vars by default."""
    config = AirpodsConfig.from_dict(deepcopy(DEFAULT_CONFIG_DICT))
    resolved = resolve_templates(config)

    # By default, auto_configure_ollama is False
    assert resolved.services["open-webui"].auto_configure_ollama is False

    # Ollama env vars should NOT be present in defaults
    assert "OLLAMA_BASE_URL" not in resolved.services["open-webui"].env
    assert "OPENAI_API_BASE_URL" not in resolved.services["open-webui"].env
    assert "OPENAI_API_KEY" not in resolved.services["open-webui"].env


def test_open_webui_ollama_integration_when_enabled():
    """Test that Open WebUI gets Ollama env vars when auto_configure_ollama is enabled."""
    config_dict = deepcopy(DEFAULT_CONFIG_DICT)
    config_dict["services"]["open-webui"]["auto_configure_ollama"] = True

    config = AirpodsConfig.from_dict(config_dict)
    resolved = resolve_templates(config)

    assert resolved.services["open-webui"].auto_configure_ollama is True


def test_llamacpp_command_args_template_resolution():
    config_dict = deepcopy(DEFAULT_CONFIG_DICT)
    config_dict["services"]["llamacpp"]["enabled"] = True

    config = AirpodsConfig.from_dict(config_dict)
    resolved = resolve_templates(config)

    model_arg = resolved.services["llamacpp"].command_args.get("model")
    assert model_arg == "/models/Qwen3.5-4B-heretic-Q4_K_M.gguf"
    assert resolved.services["llamacpp"].default_model_url == (
        "https://huggingface.co/saidutta69/Qwen3.5-4B-heretic/resolve/main/"
        "Qwen3.5-4B-heretic-Q4_K_M.gguf"
    )
