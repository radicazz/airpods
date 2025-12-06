from __future__ import annotations

from typing import Dict, List, Optional

from airpods import state
from airpods.configuration import get_config
from airpods.configuration.errors import ConfigurationError
from airpods.configuration.schema import AirpodsConfig, ServiceConfig
from airpods.services import ServiceRegistry, ServiceSpec, VolumeMount


_BIND_VOLUME_PREFIX = "bind://"


def _webui_secret_env() -> Dict[str, str]:
    return {"WEBUI_SECRET_KEY": state.ensure_webui_secret()}


def _resolve_volume_source(source: str) -> str:
    if not source:
        raise ConfigurationError("volume source cannot be empty")
    if source.startswith(_BIND_VOLUME_PREFIX):
        relative = source[len(_BIND_VOLUME_PREFIX) :].strip()
        if not relative:
            raise ConfigurationError(
                "bind:// volume sources must include a relative path (e.g. bind://comfyui/workspace)"
            )
        try:
            return str(state.resolve_volume_path(relative))
        except ValueError as exc:  # pragma: no cover - defensive guard
            raise ConfigurationError(str(exc)) from exc
    return source


def _service_spec_from_config(name: str, service: ServiceConfig) -> ServiceSpec:
    volumes = [
        VolumeMount(_resolve_volume_source(mount.source), mount.target)
        for mount in service.volumes.values()
    ]
    if name == "comfyui" and not any(
        mount.target == "/workspace" for mount in service.volumes.values()
    ):
        volumes.append(
            VolumeMount(
                _resolve_volume_source("bind://comfyui/workspace"), "/workspace"
            )
        )
    ports = [(port.host, port.container) for port in service.ports]
    env_factory = _webui_secret_env if service.needs_webui_secret else None
    return ServiceSpec(
        name=name,
        pod=service.pod,
        container=service.container,
        image=service.image,
        ports=ports,
        env=dict(service.env),
        env_factory=env_factory,
        volumes=volumes,
        network_aliases=list(service.network_aliases),
        needs_gpu=service.gpu.enabled,
        health_path=service.health.path,
    )


def _load_service_specs(config: Optional[AirpodsConfig] = None) -> List[ServiceSpec]:
    config = config or get_config()
    specs: List[ServiceSpec] = []
    
    # Check if gateway is enabled
    gateway_enabled = False
    if "gateway" in config.services:
        gateway_enabled = config.services["gateway"].enabled
    
    for name, service in config.services.items():
        if not service.enabled:
            continue
        
        spec = _service_spec_from_config(name, service)
        
        # If gateway is enabled, remove host port bindings for internal services
        # (make them internal-only on airpods_network)
        if gateway_enabled and name in ("open-webui", "ollama"):
            spec = ServiceSpec(
                name=spec.name,
                pod=spec.pod,
                container=spec.container,
                image=spec.image,
                ports=[],  # No host binding when gateway is active
                env=spec.env,
                env_factory=spec.env_factory,
                volumes=spec.volumes,
                network_aliases=spec.network_aliases,
                needs_gpu=spec.needs_gpu,
                health_path=spec.health_path,
            )
        
        specs.append(spec)
    
    return specs


REGISTRY = ServiceRegistry(_load_service_specs())


def reload_registry(config: Optional[AirpodsConfig] = None) -> ServiceRegistry:
    """Rebuild the service registry from the latest configuration."""
    global REGISTRY
    REGISTRY = ServiceRegistry(_load_service_specs(config))
    return REGISTRY
