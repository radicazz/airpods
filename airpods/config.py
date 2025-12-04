from __future__ import annotations

from typing import Dict, List

from airpods import state
from airpods.configuration import get_config
from airpods.configuration.schema import ServiceConfig
from airpods.services import ServiceRegistry, ServiceSpec, VolumeMount


def _webui_secret_env() -> Dict[str, str]:
    return {"WEBUI_SECRET_KEY": state.ensure_webui_secret()}


def _service_spec_from_config(name: str, service: ServiceConfig) -> ServiceSpec:
    volumes = [
        VolumeMount(mount.source, mount.target) for mount in service.volumes.values()
    ]
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


def _load_service_specs() -> List[ServiceSpec]:
    config = get_config()
    specs: List[ServiceSpec] = []
    for name, service in config.services.items():
        if not service.enabled:
            continue
        specs.append(_service_spec_from_config(name, service))
    return specs


REGISTRY = ServiceRegistry(_load_service_specs())
