"""ComfyUI image selection and configuration utilities."""

from __future__ import annotations

from typing import Dict, Literal, Optional, Tuple

import os

from airpods.cuda import (
    DEFAULT_CUDA_VERSION,
)


# Image provider type
ComfyProvider = Literal["yanwk", "mmartial"]

# yanwk/comfyui-boot image variants (community-maintained)
YANWK_IMAGES: Dict[str, str] = {
    "cu118": "docker.io/yanwk/comfyui-boot:cu118-slim",
    "cu126": "docker.io/yanwk/comfyui-boot:cu126-megapak",
    "cu128": "docker.io/yanwk/comfyui-boot:cu128-slim",
    "cu130": "docker.io/yanwk/comfyui-boot:cu130-slim",
    "cpu": "docker.io/yanwk/comfyui-boot:cpu",
}

# mmartial/comfyui-nvidia-docker images (GTX 10xx optimized)
# Tags are dated releases; pinning to specific known-good versions
MMARTIAL_IMAGES: Dict[str, str] = {
    "cu126": "docker.io/mmartial/comfyui-nvidia-docker:ubuntu24_cuda12.6.3-20251211",
    "cu128": "docker.io/mmartial/comfyui-nvidia-docker:ubuntu24_cuda12.8-20251211",
    "cpu": "docker.io/yanwk/comfyui-boot:cpu",  # fallback to yanwk for CPU
}


def select_provider(
    compute_cap: Optional[Tuple[int, int]],
    provider: Literal["auto", "yanwk", "mmartial"] = "auto",
) -> ComfyProvider:
    """Select appropriate ComfyUI image provider based on GPU and preference.

    Args:
        compute_cap: GPU compute capability tuple (major, minor)
        provider: User preference - "auto", "yanwk", or "mmartial"

    Returns:
        Provider to use: "yanwk" or "mmartial"
    """
    # Handle explicit provider selection (type-safe)
    if provider == "yanwk":
        return "yanwk"
    if provider == "mmartial":
        return "mmartial"

    # Auto-selection: use mmartial for Pascal (6.x) and older that benefit from CUDA 12.6
    # Use yanwk for newer GPUs (7.x+) that work well with latest CUDA
    if compute_cap:
        major, _ = compute_cap
        if major <= 6:  # Pascal (6.x) and older
            return "mmartial"

    return "yanwk"


def select_comfyui_image(
    cuda_version: Optional[str] = None,
    force_cpu: bool = False,
    provider: ComfyProvider = "yanwk",
) -> str:
    """Select appropriate ComfyUI Docker image.

    Args:
        cuda_version: CUDA version like "cu126", "cu128", etc. If None, uses default.
        force_cpu: If True, return CPU-only image.
        provider: Image provider to use.

    Returns:
        Docker image tag for ComfyUI
    """
    if force_cpu:
        return YANWK_IMAGES["cpu"]

    if not cuda_version:
        cuda_version = DEFAULT_CUDA_VERSION

    images = MMARTIAL_IMAGES if provider == "mmartial" else YANWK_IMAGES

    # Return requested CUDA image from selected provider, fallback to default
    return images.get(
        cuda_version,
        images.get(DEFAULT_CUDA_VERSION, YANWK_IMAGES[DEFAULT_CUDA_VERSION]),
    )


def get_comfyui_volumes(provider: ComfyProvider) -> Dict[str, Tuple[str, str]]:
    """Get volume mount structure for the specified provider.

    Args:
        provider: Image provider ("yanwk" or "mmartial")

    Returns:
        Dictionary mapping volume names to (source_suffix, target_path) tuples
    """
    if provider == "mmartial":
        # mmartial uses /basedir/models/ for model storage
        return {
            "basedir": ("comfyui/basedir", "/basedir"),
            "run": ("comfyui/run", "/comfy/mnt"),
            "custom_nodes": ("comfyui_custom_nodes", "/root/ComfyUI/custom_nodes"),
        }

    # yanwk default structure
    return {
        "workspace": ("comfyui/workspace", "/workspace"),
        "models": ("airpods_comfyui_data", "/root/ComfyUI/models"),
        "custom_nodes": ("comfyui_custom_nodes", "/root/ComfyUI/custom_nodes"),
    }


def get_comfyui_user_dir(provider: ComfyProvider) -> str:
    """Return the ComfyUI user directory inside the container."""
    if provider == "mmartial":
        return "/basedir/user"
    # yanwk default layout
    return "/workspace/user"


def get_default_env(provider: ComfyProvider) -> Dict[str, str]:
    """Get default environment variables for the specified provider.

    Args:
        provider: Image provider ("yanwk" or "mmartial")

    Returns:
        Dictionary of environment variables
    """
    if provider == "mmartial":
        # Auto-detect UID/GID for proper file ownership
        uid = os.getuid()
        gid = os.getgid()

        return {
            "USE_UV": "true",
            "PREINSTALL_TORCH": "true",
            "USE_PIPUPGRADE": "false",
            "BASE_DIRECTORY": "/basedir",
            "SECURITY_LEVEL": "weak",
            "CLI_ARGS": "--listen 0.0.0.0",
            "NVIDIA_VISIBLE_DEVICES": "all",
            "NVIDIA_DRIVER_CAPABILITIES": "all",
            "WANTED_UID": str(uid),
            "WANTED_GID": str(gid),
        }

    # yanwk default environment
    return {
        "CLI_ARGS": "--listen 0.0.0.0",
    }
