"""Tests for dynamic port binding based on gateway configuration."""

from __future__ import annotations

import pytest

from airpods.config import _load_service_specs
from airpods.configuration.defaults import DEFAULT_CONFIG_DICT
from airpods.configuration.schema import AirpodsConfig


def test_open_webui_has_ports_when_gateway_disabled():
    """Test Open WebUI has host port binding when gateway is disabled."""
    config_dict = DEFAULT_CONFIG_DICT.copy()
    config_dict["services"]["gateway"]["enabled"] = False
    config = AirpodsConfig.from_dict(config_dict)
    
    specs = _load_service_specs(config)
    webui_specs = [s for s in specs if s.name == "open-webui"]
    
    assert len(webui_specs) == 1
    webui = webui_specs[0]
    
    # Should have port binding (3000 -> 8080)
    assert len(webui.ports) == 1
    assert webui.ports[0] == (3000, 8080)


def test_open_webui_no_ports_when_gateway_enabled():
    """Test Open WebUI has no host port binding when gateway is enabled."""
    config_dict = DEFAULT_CONFIG_DICT.copy()
    config_dict["services"]["gateway"]["enabled"] = True
    config = AirpodsConfig.from_dict(config_dict)
    
    specs = _load_service_specs(config)
    webui_specs = [s for s in specs if s.name == "open-webui"]
    
    assert len(webui_specs) == 1
    webui = webui_specs[0]
    
    # Should have NO port binding (internal-only)
    assert webui.ports == []


def test_gateway_has_ports_when_enabled():
    """Test gateway service has port binding when enabled."""
    config_dict = DEFAULT_CONFIG_DICT.copy()
    config_dict["services"]["gateway"]["enabled"] = True
    config = AirpodsConfig.from_dict(config_dict)
    
    specs = _load_service_specs(config)
    gateway_specs = [s for s in specs if s.name == "gateway"]
    
    assert len(gateway_specs) == 1
    gateway = gateway_specs[0]
    
    # Gateway should have port binding (8080 -> 80)
    assert len(gateway.ports) == 1
    assert gateway.ports[0] == (8080, 80)


def test_other_services_unaffected_by_gateway():
    """Test ComfyUI ports are unaffected by gateway (Ollama hidden when gateway enabled)."""
    config_dict = DEFAULT_CONFIG_DICT.copy()
    config_dict["services"]["gateway"]["enabled"] = True
    config = AirpodsConfig.from_dict(config_dict)
    
    specs = _load_service_specs(config)
    
    # Ollama should have NO ports when gateway enabled (hidden)
    ollama_specs = [s for s in specs if s.name == "ollama"]
    assert len(ollama_specs) == 1
    assert ollama_specs[0].ports == []
    
    # ComfyUI should still have its ports (not yet protected)
    comfyui_specs = [s for s in specs if s.name == "comfyui"]
    assert len(comfyui_specs) == 1
    assert comfyui_specs[0].ports == [(8188, 8188)]


def test_ollama_has_ports_when_gateway_disabled():
    """Test Ollama has host port binding when gateway is disabled."""
    config_dict = DEFAULT_CONFIG_DICT.copy()
    config_dict["services"]["gateway"]["enabled"] = False
    config = AirpodsConfig.from_dict(config_dict)
    
    specs = _load_service_specs(config)
    ollama_specs = [s for s in specs if s.name == "ollama"]
    
    assert len(ollama_specs) == 1
    ollama = ollama_specs[0]
    
    # Should have port binding (11434 -> 11434)
    assert len(ollama.ports) == 1
    assert ollama.ports[0] == (11434, 11434)


def test_ollama_no_ports_when_gateway_enabled():
    """Test Ollama has no host port binding when gateway is enabled."""
    config_dict = DEFAULT_CONFIG_DICT.copy()
    config_dict["services"]["gateway"]["enabled"] = True
    config = AirpodsConfig.from_dict(config_dict)
    
    specs = _load_service_specs(config)
    ollama_specs = [s for s in specs if s.name == "ollama"]
    
    assert len(ollama_specs) == 1
    ollama = ollama_specs[0]
    
    # Should have NO port binding (internal-only)
    assert ollama.ports == []


def test_open_webui_retains_other_properties_when_gateway_enabled():
    """Test Open WebUI retains all other properties when gateway removes ports."""
    config_dict = DEFAULT_CONFIG_DICT.copy()
    config_dict["services"]["gateway"]["enabled"] = True
    config = AirpodsConfig.from_dict(config_dict)
    
    specs = _load_service_specs(config)
    webui = [s for s in specs if s.name == "open-webui"][0]
    
    # Verify other properties are unchanged
    assert webui.name == "open-webui"
    assert webui.pod == "open-webui"
    assert webui.container == "open-webui-0"
    assert webui.image == "ghcr.io/open-webui/open-webui:latest"
    assert "webui" in webui.network_aliases
    assert "open-webui" in webui.network_aliases
    assert webui.health_path == "/"
    assert len(webui.volumes) == 2  # data + plugins
    assert webui.env_factory is not None  # needs_webui_secret
