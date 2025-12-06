from __future__ import annotations

from typing import Dict, List, Optional

from airpods import state
from airpods.configuration import get_config
from airpods.configuration.errors import ConfigurationError
from airpods.configuration.schema import AirpodsConfig, ServiceConfig
from airpods.services import ServiceRegistry, ServiceSpec, VolumeMount
from airpods.cuda import select_cuda_version, select_comfyui_image
from airpods.system import detect_cuda_compute_capability
from airpods.logging import console


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


def _resolve_cuda_image(
    name: str, service: ServiceConfig, config: AirpodsConfig
) -> str:
    """Resolve CUDA-specific image for ComfyUI service based on GPU capability detection."""
    if name != "comfyui":
        return service.image

    # Priority chain: service override → runtime setting → auto-detection → fallback
    selected_cuda_version = None
    selection_source = None

    if service.cuda_override:
        selected_cuda_version = service.cuda_override
        selection_source = f"service override ({service.cuda_override})"
    elif config.runtime.cuda_version != "auto":
        selected_cuda_version = config.runtime.cuda_version
        selection_source = f"runtime setting ({config.runtime.cuda_version})"
    else:
        # Auto-detection
        has_gpu, gpu_name, compute_cap = detect_cuda_compute_capability()
        if has_gpu and compute_cap:
            selected_cuda_version = select_cuda_version(compute_cap)
            major, minor = compute_cap
            selection_source = (
                f"auto-detected (compute {major}.{minor} → {selected_cuda_version})"
            )
        else:
            # Fallback to cu126 (backwards compatible default)
            selected_cuda_version = "cu126"
            selection_source = f"fallback (GPU detection failed: {gpu_name})"

    # Force CPU if GPU is disabled for this service
    force_cpu = service.gpu.force_cpu or not service.gpu.enabled
    resolved_image = select_comfyui_image(selected_cuda_version, force_cpu=force_cpu)

    # Log the selection for transparency
    if resolved_image != service.image:
        console.print(f"[info]ComfyUI CUDA: {selection_source} → {resolved_image}[/]")

    return resolved_image


def _service_spec_from_config(
    name: str, service: ServiceConfig, config: AirpodsConfig
) -> ServiceSpec:
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

    # Resolve CUDA-aware image for ComfyUI
    resolved_image = _resolve_cuda_image(name, service, config)

    return ServiceSpec(
        name=name,
        pod=service.pod,
        container=service.container,
        image=resolved_image,
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
    for name, service in config.services.items():
        if not service.enabled:
            continue
        specs.append(_service_spec_from_config(name, service, config))
    return specs


REGISTRY = ServiceRegistry(_load_service_specs())


def reload_registry(config: Optional[AirpodsConfig] = None) -> ServiceRegistry:
    """Rebuild the service registry from the latest configuration."""
    global REGISTRY
    REGISTRY = ServiceRegistry(_load_service_specs(config))
    return REGISTRY
