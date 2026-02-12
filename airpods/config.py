from __future__ import annotations

import os
from typing import Dict, List, Optional

from airpods import state
from airpods.configuration import get_config
from airpods.configuration.errors import ConfigurationError
from airpods.configuration.schema import AirpodsConfig, ServiceConfig, CommandArgValue
from airpods.services import ServiceRegistry, ServiceSpec, VolumeMount
from airpods.cuda import select_cuda_version
from airpods.comfyui import (
    ComfyProvider,
    get_comfyui_user_dir,
    get_comfyui_volumes,
    get_default_env,
    select_comfyui_image,
    select_provider,
)
from airpods.system import detect_cuda_compute_capability
from airpods.logging import console


ENABLE_COMFY_CUDA_LOG = False


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

    # Detect GPU capability for provider selection
    has_gpu, gpu_name, compute_cap = detect_cuda_compute_capability()

    if service.cuda_override:
        selected_cuda_version = service.cuda_override
        selection_source = f"service override ({service.cuda_override})"
    elif config.runtime.cuda_version != "auto":
        selected_cuda_version = config.runtime.cuda_version
        selection_source = f"runtime setting ({config.runtime.cuda_version})"
    else:
        # Auto-detection
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

    # Select provider (yanwk vs mmartial) based on GPU capability
    # Respects user preference from config, or auto-selects based on GPU
    provider_pref = config.runtime.comfyui_provider
    provider = select_provider(compute_cap, provider_pref)

    # Force CPU if GPU is disabled for this service
    force_cpu = service.gpu.force_cpu or not service.gpu.enabled
    resolved_image = select_comfyui_image(
        selected_cuda_version, force_cpu=force_cpu, provider=provider
    )

    # Log the selection for transparency
    if ENABLE_COMFY_CUDA_LOG and resolved_image != service.image:
        console.print(f"[info]ComfyUI CUDA: {selection_source} → {resolved_image}[/]")

    return resolved_image


def _derive_llamacpp_cpu_image(image: str) -> str:
    if image.startswith("ghcr.io/ggerganov/llama.cpp"):
        image = image.replace(
            "ghcr.io/ggerganov/llama.cpp", "ghcr.io/ggml-org/llama.cpp", 1
        )
    if "server-cuda" in image:
        return image.replace("server-cuda", "server")
    if image.endswith("-cuda"):
        return image[: -len("-cuda")]
    return image


def _derive_llamacpp_gpu_image(image: str) -> str:
    if image.startswith("ghcr.io/ggerganov/llama.cpp"):
        image = image.replace(
            "ghcr.io/ggerganov/llama.cpp", "ghcr.io/ggml-org/llama.cpp", 1
        )
    if "server-cuda" in image or image.endswith("-cuda"):
        return image
    if ":server" in image:
        return image.replace(":server", ":server-cuda")
    return image


def _resolve_service_image(
    name: str, service: ServiceConfig, config: AirpodsConfig
) -> tuple[str, Optional[str]]:
    if name == "comfyui":
        return _resolve_cuda_image(name, service, config), None
    if name == "llamacpp":
        original_image = service.image
        cpu_image = _derive_llamacpp_cpu_image(service.image)
        if original_image != cpu_image and original_image.startswith(
            "ghcr.io/ggerganov/llama.cpp"
        ):
            console.print(
                "[info]llamacpp: switching image to ghcr.io/ggml-org/llama.cpp (updated registry)[/]"
            )
        use_gpu = (
            service.gpu.enabled
            and not service.gpu.force_cpu
            and config.runtime.cuda_version != "cpu"
        )
        if use_gpu:
            return _derive_llamacpp_gpu_image(service.image), cpu_image
        return cpu_image, cpu_image
    return service.image, None


def _snake_to_kebab(name: str) -> str:
    return name.replace("_", "-")


def _render_command_args(command_args: Dict[str, CommandArgValue]) -> List[str]:
    args: List[str] = []
    for key, value in command_args.items():
        flag = f"--{_snake_to_kebab(key)}"
        if isinstance(value, bool):
            if value:
                args.append(flag)
            continue
        if value is None:
            continue
        if isinstance(value, list):
            for item in value:
                args.append(flag)
                args.append(str(item))
            continue
        args.append(flag)
        args.append(str(value))
    return args


def _service_command_parts(service: ServiceConfig) -> tuple[Optional[str], List[str]]:
    entrypoint_override = service.entrypoint_override or []
    entrypoint = entrypoint_override[0] if entrypoint_override else None
    base_args = entrypoint_override[1:] if entrypoint_override else []
    command_args = _render_command_args(service.command_args or {})
    return entrypoint, base_args + command_args


def _get_comfyui_provider(config: AirpodsConfig):
    """Detect ComfyUI provider based on GPU capability and config."""
    has_gpu, gpu_name, compute_cap = detect_cuda_compute_capability()
    # Use runtime.comfyui_provider setting (defaults to "auto")
    provider_pref = config.runtime.comfyui_provider
    return select_provider(compute_cap, provider_pref)


def _get_comfyui_provider_env(config: AirpodsConfig) -> Dict[str, str]:
    """Get provider-specific environment variables for ComfyUI."""
    provider = _get_comfyui_provider(config)
    return get_default_env(provider)


def _service_spec_from_config(
    name: str, service: ServiceConfig, config: AirpodsConfig
) -> ServiceSpec:
    provider: ComfyProvider | None = None

    # Handle ComfyUI provider-specific volumes
    if name == "comfyui":
        provider = _get_comfyui_provider(config)
        provider_volumes = get_comfyui_volumes(provider)

        # Build volumes from config, then add provider-specific defaults
        volumes = []
        for vol_name, mount in service.volumes.items():
            volumes.append(
                VolumeMount(_resolve_volume_source(mount.source), mount.target)
            )

        # Add provider-specific volumes if not already configured
        configured_targets = {vol.target for vol in volumes}
        for vol_name, (source_suffix, target) in provider_volumes.items():
            if target not in configured_targets:
                volumes.append(
                    VolumeMount(
                        _resolve_volume_source(f"bind://{source_suffix}"), target
                    )
                )
    else:
        # Non-ComfyUI services use standard volume handling
        volumes = [
            VolumeMount(_resolve_volume_source(mount.source), mount.target)
            for mount in service.volumes.values()
        ]

    ports = [(port.host, port.container) for port in service.ports]
    env_factory = _webui_secret_env if service.needs_webui_secret else None

    # Resolve image selection (ComfyUI/llamacpp-specific handling)
    resolved_image, cpu_image = _resolve_service_image(name, service, config)

    # Build environment variables with provider-specific defaults
    env = dict(service.env)
    if name == "comfyui":
        # Add provider-specific environment variables (mmartial needs extra env vars)
        provider_env = get_default_env(provider or _get_comfyui_provider(config))
        # User-configured env takes precedence over provider defaults
        for key, value in provider_env.items():
            if key not in env:
                env[key] = value

        # Ensure user data (workflows, settings) lives on the mounted workspace/basedir.
        # Only yanwk needs this override; mmartial already uses /basedir.
        if (provider or _get_comfyui_provider(config)) == "yanwk":
            command_args = dict(service.command_args)
            if "user_directory" not in command_args:
                command_args["user_directory"] = get_comfyui_user_dir(
                    provider or _get_comfyui_provider(config)
                )
                updates = {"command_args": command_args}
                if not service.entrypoint_override:
                    updates["entrypoint_override"] = [
                        "bash",
                        "/runner-scripts/entrypoint.sh",
                    ]
                service = service.model_copy(update=updates)

        custom_nodes_target = None
        for mount in volumes:
            if mount.target.endswith("/custom_nodes"):
                custom_nodes_target = mount.target
                break
        if custom_nodes_target:
            site_packages = f"{custom_nodes_target.rstrip('/')}/.airpods/site-packages"
            existing = env.get("PYTHONPATH")
            if existing:
                parts = [p for p in existing.split(os.pathsep) if p]
                if site_packages not in parts:
                    env["PYTHONPATH"] = existing + os.pathsep + site_packages
            else:
                env["PYTHONPATH"] = site_packages

    # Conditionally inject Ollama configuration for open-webui service
    if name == "open-webui" and service.auto_configure_ollama:
        ollama_service = config.services.get("ollama")
        if ollama_service and ollama_service.ports:
            ollama_port = ollama_service.ports[0].host
            env.update(
                {
                    "OLLAMA_BASE_URL": f"http://localhost:{ollama_port}",
                    "OPENAI_API_BASE_URL": f"http://localhost:{ollama_port}/v1",
                    "OPENAI_API_KEY": "ollama",
                }
            )

    # Set userns_mode for mmartial ComfyUI (needs keep-id for proper file ownership at pod level)
    userns_mode = None
    if name == "comfyui":
        provider = provider or _get_comfyui_provider(config)
        if provider == "mmartial":
            userns_mode = "keep-id"

    entrypoint, command_args = _service_command_parts(service)
    command: Optional[List[str]] = None

    if name == "llamacpp":
        if entrypoint is None:
            entrypoint = "/app/llama-server"
        command = command_args or None
    elif entrypoint is not None or command_args:
        command = command_args or None

    needs_gpu = (
        service.gpu.enabled
        and not service.gpu.force_cpu
        and config.runtime.cuda_version != "cpu"
    )

    return ServiceSpec(
        name=name,
        pod=service.pod,
        container=service.container,
        image=resolved_image,
        ports=ports,
        env=env,
        env_factory=env_factory,
        volumes=volumes,
        pids_limit=service.pids_limit,
        needs_gpu=needs_gpu,
        health_path=service.health.path,
        health_expected_status=service.health.expected_status,
        force_cpu=service.gpu.force_cpu,
        userns_mode=userns_mode,
        entrypoint=entrypoint,
        command=command,
        cpu_image=cpu_image,
        memory=service.resources.memory,
        cpus=service.resources.cpus,
    )


def load_service_specs(
    config: Optional[AirpodsConfig] = None, *, include_disabled: bool = False
) -> List[ServiceSpec]:
    """Return service specs from config, optionally including disabled services."""
    config = config or get_config()
    specs: List[ServiceSpec] = []
    for name, service in config.services.items():
        if not include_disabled and not service.enabled:
            continue
        specs.append(_service_spec_from_config(name, service, config))
    return specs


REGISTRY = ServiceRegistry(load_service_specs())


def reload_registry(config: Optional[AirpodsConfig] = None) -> ServiceRegistry:
    """Rebuild the service registry from the latest configuration."""
    global REGISTRY
    REGISTRY = ServiceRegistry(load_service_specs(config))
    return REGISTRY
