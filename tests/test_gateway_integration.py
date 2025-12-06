"""Integration tests for gateway service.

Note: These are simplified tests that don't require Podman.
Full integration tests with actual containers should be run manually.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from airpods.config import _load_service_specs
from airpods.configuration.defaults import DEFAULT_CONFIG_DICT
from airpods.configuration.schema import AirpodsConfig
from airpods.configuration.resolver import resolve_caddyfile_template
from airpods import state


def test_gateway_end_to_end_config_flow():
    """Test complete gateway configuration flow."""
    # Enable gateway
    config_dict = DEFAULT_CONFIG_DICT.copy()
    config_dict["services"]["gateway"]["enabled"] = True
    config = AirpodsConfig.from_dict(config_dict)
    
    # Load service specs
    specs = _load_service_specs(config)
    service_names = [s.name for s in specs]
    
    # Verify gateway is included
    assert "gateway" in service_names
    
    # Find gateway spec
    gateway = [s for s in specs if s.name == "gateway"][0]
    
    # Verify gateway configuration
    assert gateway.pod == "gateway"
    assert gateway.container == "caddy-0"
    assert gateway.image == "docker.io/caddy:2.8-alpine"
    assert gateway.ports == [(8080, 80)]
    assert "gateway" in gateway.network_aliases
    assert "caddy" in gateway.network_aliases
    
    # Verify Open WebUI has no host ports (internal only)
    webui = [s for s in specs if s.name == "open-webui"][0]
    assert webui.ports == []


def test_caddyfile_template_resolution():
    """Test Caddyfile template resolves correctly."""
    config = AirpodsConfig.from_dict(DEFAULT_CONFIG_DICT)
    
    # Sample template content
    template = """
:{{services.gateway.ports.0.container}} {
  reverse_proxy open-webui:{{services.open-webui.ports.0.container}}
}
""".strip()
    
    # Resolve
    resolved = resolve_caddyfile_template(template, config)
    
    # Verify substitution
    assert ":80 {" in resolved
    assert "open-webui:8080" in resolved
    assert "{{" not in resolved  # No unresolved templates


def test_gateway_caddyfile_generation(tmp_path: Path):
    """Test Caddyfile generation and writing."""
    state.set_state_root(tmp_path)
    
    try:
        # Sample resolved content
        content = """
{
  auto_https off
  admin off
}

:80 {
  reverse_proxy open-webui:8080
}
""".strip()
        
        # Write Caddyfile
        path = state.ensure_gateway_caddyfile(content)
        
        # Verify path
        expected = tmp_path / "volumes/gateway/Caddyfile"
        assert path == expected
        
        # Verify file exists
        assert path.exists()
        
        # Verify content
        written = path.read_text(encoding="utf-8")
        assert written == content
        
    finally:
        state.clear_state_root_override()


def test_gateway_volumes_configuration():
    """Test gateway volume mounts are configured correctly."""
    config_dict = DEFAULT_CONFIG_DICT.copy()
    config_dict["services"]["gateway"]["enabled"] = True
    config = AirpodsConfig.from_dict(config_dict)
    
    specs = _load_service_specs(config)
    gateway = [s for s in specs if s.name == "gateway"][0]
    
    # Check volumes
    assert len(gateway.volumes) == 2
    
    # Config volume (readonly Caddyfile)
    config_volume = [v for v in gateway.volumes if "/etc/caddy/Caddyfile" in v.target][0]
    assert "gateway/Caddyfile" in config_volume.source
    assert config_volume.target == "/etc/caddy/Caddyfile"
    
    # Data volume
    data_volume = [v for v in gateway.volumes if "/data" in v.target][0]
    assert "gateway/data" in data_volume.source
    assert data_volume.target == "/data"


@pytest.mark.parametrize(
    "service_name,should_have_ports",
    [
        ("gateway", True),
        ("open-webui", False),
        ("ollama", False),  # Ollama hidden when gateway enabled
        ("comfyui", True),
    ],
)
def test_gateway_port_behavior(service_name: str, should_have_ports: bool):
    """Test port binding behavior with gateway enabled."""
    config_dict = DEFAULT_CONFIG_DICT.copy()
    config_dict["services"]["gateway"]["enabled"] = True
    config = AirpodsConfig.from_dict(config_dict)
    
    specs = _load_service_specs(config)
    service = [s for s in specs if s.name == service_name][0]
    
    if should_have_ports:
        assert len(service.ports) > 0, f"{service_name} should have ports"
    else:
        assert len(service.ports) == 0, f"{service_name} should NOT have ports"
