"""Tests for airpods.config module."""

from __future__ import annotations

from copy import deepcopy

import pytest

from airpods.config import _service_spec_from_config, reload_registry
from airpods.configuration.defaults import DEFAULT_CONFIG_DICT
from airpods.configuration.schema import AirpodsConfig


def test_open_webui_no_ollama_env_by_default():
    """Test that Open WebUI ServiceSpec doesn't include Ollama env vars by default."""
    config = AirpodsConfig.from_dict(deepcopy(DEFAULT_CONFIG_DICT))

    spec = _service_spec_from_config(
        "open-webui", config.services["open-webui"], config
    )

    # Ollama env vars should NOT be present
    assert "OLLAMA_BASE_URL" not in spec.env
    assert "OPENAI_API_BASE_URL" not in spec.env
    assert "OPENAI_API_KEY" not in spec.env

    # Basic env vars should still be present
    assert "PORT" in spec.env
    assert spec.env["PORT"] == "{{services.open-webui.ports.0.host}}"


def test_open_webui_ollama_env_when_enabled():
    """Test that Open WebUI ServiceSpec includes Ollama env vars when flag is enabled."""
    config_dict = deepcopy(DEFAULT_CONFIG_DICT)
    config_dict["services"]["open-webui"]["auto_configure_ollama"] = True

    config = AirpodsConfig.from_dict(config_dict)
    spec = _service_spec_from_config(
        "open-webui", config.services["open-webui"], config
    )

    # Ollama env vars should be present
    assert spec.env["OLLAMA_BASE_URL"] == "http://localhost:11434"
    assert spec.env["OPENAI_API_BASE_URL"] == "http://localhost:11434/v1"
    assert spec.env["OPENAI_API_KEY"] == "ollama"

    # Basic env vars should still be present
    assert "PORT" in spec.env


def test_open_webui_ollama_env_with_custom_port():
    """Test that Ollama env vars use the correct port from config."""
    config_dict = deepcopy(DEFAULT_CONFIG_DICT)
    config_dict["services"]["open-webui"]["auto_configure_ollama"] = True
    config_dict["services"]["ollama"]["ports"][0]["host"] = 12345

    config = AirpodsConfig.from_dict(config_dict)
    spec = _service_spec_from_config(
        "open-webui", config.services["open-webui"], config
    )

    # Ollama env vars should use custom port
    assert spec.env["OLLAMA_BASE_URL"] == "http://localhost:12345"
    assert spec.env["OPENAI_API_BASE_URL"] == "http://localhost:12345/v1"


def test_reload_registry_respects_auto_configure_flag():
    """Test that registry reload properly handles auto_configure_ollama."""
    config_dict = deepcopy(DEFAULT_CONFIG_DICT)
    config_dict["services"]["open-webui"]["auto_configure_ollama"] = False

    config = AirpodsConfig.from_dict(config_dict)
    registry = reload_registry(config)

    webui_spec = registry.get("open-webui")
    assert webui_spec is not None
    assert "OLLAMA_BASE_URL" not in webui_spec.env

    # Now enable it
    config_dict["services"]["open-webui"]["auto_configure_ollama"] = True
    config = AirpodsConfig.from_dict(config_dict)
    registry = reload_registry(config)

    webui_spec = registry.get("open-webui")
    assert webui_spec is not None
    assert webui_spec.env["OLLAMA_BASE_URL"] == "http://localhost:11434"


def test_other_services_unaffected_by_ollama_flag():
    """Test that the auto_configure_ollama flag only affects open-webui."""
    config_dict = deepcopy(DEFAULT_CONFIG_DICT)
    config_dict["services"]["open-webui"]["auto_configure_ollama"] = True

    config = AirpodsConfig.from_dict(config_dict)

    # Ollama service should be unaffected
    ollama_spec = _service_spec_from_config("ollama", config.services["ollama"], config)
    assert "OLLAMA_BASE_URL" not in ollama_spec.env

    # ComfyUI service should be unaffected
    comfyui_spec = _service_spec_from_config(
        "comfyui", config.services["comfyui"], config
    )
    assert "OLLAMA_BASE_URL" not in comfyui_spec.env


def test_llamacpp_command_args_rendering():
    config_dict = deepcopy(DEFAULT_CONFIG_DICT)
    config_dict["services"]["llamacpp"]["enabled"] = True
    config_dict["services"]["llamacpp"]["command_args"] = {
        "model": "/models/foo.gguf",
        "ctx_size": 4096,
        "log_disable": True,
        "stop": ["\\n\\n", "###"],
        "threads": 8,
        "debug": False,
    }

    config = AirpodsConfig.from_dict(config_dict)
    spec = _service_spec_from_config("llamacpp", config.services["llamacpp"], config)

    assert spec.entrypoint == "/app/llama-server"
    assert spec.command == [
        "--model",
        "/models/foo.gguf",
        "--ctx-size",
        "4096",
        "--log-disable",
        "--stop",
        "\\n\\n",
        "--stop",
        "###",
        "--threads",
        "8",
    ]
    assert "--debug" not in spec.command


def test_service_spec_includes_health_status_range_and_resources():
    config_dict = deepcopy(DEFAULT_CONFIG_DICT)
    config_dict["services"]["open-webui"]["health"]["expected_status"] = [200, 399]
    config_dict["services"]["open-webui"]["resources"]["memory"] = "2g"
    config_dict["services"]["open-webui"]["resources"]["cpus"] = "1.5"

    config = AirpodsConfig.from_dict(config_dict)
    spec = _service_spec_from_config(
        "open-webui", config.services["open-webui"], config
    )

    assert spec.health_expected_status == (200, 399)
    assert spec.memory == "2g"
    assert spec.cpus == "1.5"
