"""CUDA version detection and ComfyUI image selection utilities."""

from __future__ import annotations

from typing import Dict, Optional, Tuple


# Compute capability → CUDA version mapping
# Based on NVIDIA CUDA compatibility: https://developer.nvidia.com/cuda-gpus
CUDA_COMPATIBILITY_MAP: Dict[Tuple[int, int], str] = {
    # Compute 3.5-5.2 (Kepler, Maxwell, Pascal gen1) - max CUDA 11.8
    (3, 5): "cu118",
    (3, 7): "cu118",
    (5, 0): "cu118",
    (5, 2): "cu118",
    (5, 3): "cu118",
    # Compute 6.0-7.5 (Pascal, Volta, Turing) - max CUDA 12.6
    (6, 0): "cu126",
    (6, 1): "cu126",
    (6, 2): "cu126",
    (7, 0): "cu126",
    (7, 2): "cu126",
    (7, 5): "cu126",
    # Compute 8.0-8.9 (Ampere) - max CUDA 12.8
    (8, 0): "cu128",
    (8, 6): "cu128",
    (8, 7): "cu128",
    (8, 9): "cu128",
    # Compute 9.0+ (Hopper and newer) - CUDA 13.0+
    (9, 0): "cu130",
}

# ComfyUI image variants available
COMFYUI_IMAGES: Dict[str, str] = {
    "cu118": "docker.io/yanwk/comfyui-boot:cu118-slim",  # fallback to cu126 if not available
    "cu126": "docker.io/yanwk/comfyui-boot:cu126-megapak",  # Safe backwards-compatible default
    "cu128": "docker.io/yanwk/comfyui-boot:cu128-slim",
    "cu130": "docker.io/yanwk/comfyui-boot:cu130-slim",
    "cpu": "docker.io/yanwk/comfyui-boot:cpu",
}

# Default fallback CUDA version (backwards compatible with most GPUs)
DEFAULT_CUDA_VERSION = "cu126"


def select_cuda_version(compute_cap: Optional[Tuple[int, int]]) -> str:
    """Select appropriate CUDA version based on GPU compute capability.

    Args:
        compute_cap: Tuple of (major, minor) compute capability, e.g., (7, 5) for compute 7.5

    Returns:
        CUDA version string like "cu126", "cu128", etc.
        Defaults to "cu126" if compute_cap is None or not found in mapping.
    """
    if not compute_cap:
        return DEFAULT_CUDA_VERSION

    # Direct lookup first
    if compute_cap in CUDA_COMPATIBILITY_MAP:
        return CUDA_COMPATIBILITY_MAP[compute_cap]

    # Fallback: find highest compatible version for this major.minor
    major, minor = compute_cap
    best_cuda = None

    # Look for compatible versions in descending order of capability
    for (cap_major, cap_minor), cuda_version in CUDA_COMPATIBILITY_MAP.items():
        if cap_major == major:
            # Same major version - check if this minor is compatible
            if cap_minor <= minor:
                # This capability is supported, use its CUDA version
                if best_cuda is None:
                    best_cuda = cuda_version
                else:
                    # Prefer newer CUDA versions when multiple are compatible
                    if _cuda_version_newer(cuda_version, best_cuda):
                        best_cuda = cuda_version
        elif cap_major < major:
            # Older major version is definitely compatible
            if best_cuda is None:
                best_cuda = cuda_version
            elif _cuda_version_newer(cuda_version, best_cuda):
                best_cuda = cuda_version

    return best_cuda or DEFAULT_CUDA_VERSION


def _cuda_version_newer(version1: str, version2: str) -> bool:
    """Return True if version1 is newer than version2."""
    # Extract numeric version: "cu126" -> 126
    try:
        num1 = int(version1[2:]) if version1.startswith("cu") else 0
        num2 = int(version2[2:]) if version2.startswith("cu") else 0
        return num1 > num2
    except ValueError:
        return False


def select_comfyui_image(
    cuda_version: Optional[str] = None, force_cpu: bool = False
) -> str:
    """Select appropriate ComfyUI Docker image based on CUDA version.

    Args:
        cuda_version: CUDA version like "cu126", "cu128", etc. If None, auto-detect.
        force_cpu: If True, return CPU-only image regardless of cuda_version.

    Returns:
        Docker image tag for ComfyUI
    """
    if force_cpu:
        return COMFYUI_IMAGES["cpu"]

    if not cuda_version:
        cuda_version = DEFAULT_CUDA_VERSION

    # Return requested CUDA image, fallback to default if not found
    return COMFYUI_IMAGES.get(cuda_version, COMFYUI_IMAGES[DEFAULT_CUDA_VERSION])


def get_cuda_info_display(
    has_gpu: bool,
    gpu_name: str,
    compute_cap: Optional[Tuple[int, int]],
    selected_cuda: str,
) -> str:
    """Format CUDA detection info for CLI display.

    Returns:
        Human-readable string like "CUDA 12.6 (cu126) for compute 7.5"
    """
    if not has_gpu:
        return f"not available ({gpu_name})"

    if compute_cap is None:
        return f"selected {selected_cuda} (compute capability unknown)"

    major, minor = compute_cap
    compute_str = f"{major}.{minor}"

    # Map CUDA version to human-readable version
    cuda_display = {
        "cu118": "CUDA 11.8",
        "cu126": "CUDA 12.6",
        "cu128": "CUDA 12.8",
        "cu130": "CUDA 13.0",
    }.get(selected_cuda, selected_cuda)

    return f"{cuda_display} ({selected_cuda}) for compute {compute_str}"
