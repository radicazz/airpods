from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class ServiceSpec:
    name: str
    pod: str
    container: str
    image: str
    ports: List[Tuple[int, int]] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    volumes: List[Tuple[str, str]] = field(default_factory=list)  # host path -> container path
    needs_gpu: bool = False
    health_path: Optional[str] = None
    health_scheme: str = "http"
    health_verify_tls: bool = True
    is_infrastructure: bool = False
    command: Optional[List[str]] = None
    optional: bool = False


# Project structure - all data is local and portable
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
VOLUMES_DIR = PROJECT_ROOT / "volumes"
DATA_OLLAMA = VOLUMES_DIR / "data-ollama"
DATA_OPENWEBUI = VOLUMES_DIR / "data-open-webui"
DATA_COMFYUI = VOLUMES_DIR / "data-comfyui"
DATA_COMFYUI_RUN = VOLUMES_DIR / "comfyui-run"
DATA_SHARED = VOLUMES_DIR / "shared"
DATA_CADDY = VOLUMES_DIR / "caddy-data"
CONFIG_DIR = PROJECT_ROOT / "config"
COMFYUI_CONFIG = CONFIG_DIR / "comfyui"
CADDY_CONFIG = str(CONFIG_DIR)
CADDY_DATA = str(DATA_CADDY)
CLOUDFLARED_CONFIG = CONFIG_DIR / "cloudflared.yml"
CLOUDFLARED_TEMPLATE = CONFIG_DIR / "cloudflared.yml.template"
CLOUDFLARED_VOLUME = VOLUMES_DIR / "cloudflared"

# Volume paths (absolute paths for bind mounts)
OLLAMA_VOLUME = str(DATA_OLLAMA)
OPENWEBUI_VOLUME = str(DATA_OPENWEBUI)
COMFYUI_VOLUME = str(DATA_COMFYUI)

# Portal paths
PORTAL_DIR = PROJECT_ROOT / "portal"


def get_comfyui_image(cuda_capability: Optional[str] = None) -> str:
    """Select appropriate ComfyUI Docker image based on CUDA compute capability.
    
    Args:
        cuda_capability: CUDA compute capability string (e.g., "6.1", "7.5", "8.9")
    
    Returns:
        Docker image string for ComfyUI (mmartial/comfyui-nvidia-docker)
    
    Notes:
        - Uses mmartial/comfyui-nvidia-docker (simpler, no auth layer)
        - CUDA 12.8 for Blackwell GPUs (RTX 50xx, capability >= 8.9)
        - CUDA 12.6.3 for most GPUs (default/latest)
        - CUDA 12.3.2 for older GPUs (capability < 7.0, e.g., GTX 1070)
    """
    base = "docker.io/mmartial/comfyui-nvidia-docker"
    
    if cuda_capability is None:
        # No GPU or capability unknown - use latest stable (12.6.3)
        return f"{base}:ubuntu24_cuda12.6.3-latest"
    
    try:
        # Parse capability version (e.g., "8.9" -> 8.9)
        capability_float = float(cuda_capability)
        
        # Blackwell GPUs (RTX 50xx series) - need CUDA 12.8+
        if capability_float >= 8.9:
            return f"{base}:ubuntu24_cuda12.8-latest"
        
        # Older GPUs (GTX 10xx series) - use CUDA 12.3.2
        elif capability_float < 7.0:
            return f"{base}:ubuntu22_cuda12.3.2-latest"
        
        # Most modern GPUs - use CUDA 12.6.3 (default/latest)
        else:
            return f"{base}:ubuntu24_cuda12.6.3-latest"
            
    except (ValueError, TypeError):
        # Invalid capability format - default to latest stable
        return f"{base}:ubuntu24_cuda12.6.3-latest"


SERVICES: Dict[str, ServiceSpec] = {
    "portal": ServiceSpec(
        name="portal",
        pod="airpod-portal",
        container="airpod-portal-0",
        image="docker.io/library/python:3.11-slim",
        ports=[(8000, 8000)],
        env={
            "FLASK_APP": "app.py",
            "PORTAL_SECRET_KEY": "change-me-in-production",
        },
        volumes=[(str(PORTAL_DIR), "/app")],
        needs_gpu=False,
        health_path="/health",
        is_infrastructure=True,
    ),
    "caddy": ServiceSpec(
        name="caddy",
        pod="airpod-caddy",
        container="airpod-caddy-0",
        image="docker.io/library/caddy:2-alpine",
        ports=[(8443, 8443), (8444, 8444), (8080, 8080)],
        env={},
        volumes=[(CADDY_CONFIG, "/etc/caddy"), (CADDY_DATA, "/data")],
        needs_gpu=False,
        health_path="/",
        health_scheme="https",
        health_verify_tls=False,
        is_infrastructure=True,
    ),
    "cloudflared": ServiceSpec(
        name="cloudflared",
        pod="airpod-cloudflared",
        container="airpod-cloudflared-0",
        image="docker.io/cloudflare/cloudflared:latest",
        env={},
        volumes=[(str(CONFIG_DIR), "/config"), (str(CLOUDFLARED_VOLUME), "/etc/cloudflared")],
        needs_gpu=False,
        is_infrastructure=True,
        command=["tunnel", "--config", "/config/cloudflared.yml", "run"],
        optional=True,
    ),
    "cloudflared-quick": ServiceSpec(
        name="cloudflared-quick",
        pod="airpod-cloudflared-quick",
        container="airpod-cloudflared-quick-0",
        image="docker.io/cloudflare/cloudflared:latest",
        env={},
        volumes=[],
        needs_gpu=False,
        is_infrastructure=True,
        command=["tunnel", "--url", "https://host.containers.internal:8443", "--no-autoupdate"],
        optional=True,
    ),
    "ollama": ServiceSpec(
        name="ollama",
        pod="airpod-ollama",
        container="airpod-ollama-0",
        image="docker.io/ollama/ollama:latest",
        ports=[(11434, 11434)],
        env={
            "OLLAMA_ORIGINS": "*",
            "OLLAMA_HOST": "0.0.0.0",
        },
        volumes=[(OLLAMA_VOLUME, "/root/.ollama")],
        needs_gpu=True,
        health_path="/api/tags",
    ),
    "open-webui": ServiceSpec(
        name="open-webui",
        pod="airpod-open-webui",
        container="airpod-open-webui-0",
        image="ghcr.io/open-webui/open-webui:latest",
        ports=[(3000, 8080)],
        env={
            # Reach Ollama via the host-published port.
            "OLLAMA_BASE_URL": "http://host.containers.internal:11434",
        },
        volumes=[(OPENWEBUI_VOLUME, "/app/backend/data")],
        health_path="/",
    ),
    "comfyui": ServiceSpec(
        name="comfyui",
        pod="airpod-comfyui",
        container="airpod-comfyui-0",
        image="docker.io/mmartial/comfyui-nvidia-docker:ubuntu24_cuda12.6.3-latest",  # Default - updated dynamically at runtime
        ports=[(8188, 8188)],
        env={
            "BASE_DIRECTORY": "/basedir",
            "SECURITY_LEVEL": "normal",
            # WANTED_UID and WANTED_GID will be set at runtime
        },
        volumes=[
            (str(DATA_COMFYUI_RUN), "/comfy/mnt"),  # venv + ComfyUI source
            (str(DATA_COMFYUI), "/basedir"),         # models + user data
        ],
        needs_gpu=True,
        health_path="/",
    ),
}


def list_service_names() -> List[str]:
    return list(SERVICES.keys())


def get_service(name: str) -> Optional[ServiceSpec]:
    return SERVICES.get(name)


def ensure_caddyfile(use_portal: bool = False) -> None:
    """Generate Caddyfile from template.
    
    Args:
        use_portal: If True, use portal template with path-based routing.
                   If False, use legacy template with port-based routing.
    """
    caddyfile_path = CONFIG_DIR / "Caddyfile"
    
    # Select template based on mode
    if use_portal:
        template_path = CONFIG_DIR / "Caddyfile.portal.template"
    else:
        template_path = CONFIG_DIR / "Caddyfile.template"
    
    if not template_path.exists():
        raise RuntimeError(f"Caddyfile template not found at {template_path}")
    
    # Always regenerate when switching modes
    caddyfile_path.write_text(template_path.read_text())


def generate_self_signed_cert() -> None:
    """Generate self-signed certificate for HTTPS if it doesn't exist."""
    cert_dir = CONFIG_DIR / "certs"
    cert_file = cert_dir / "localhost.crt"
    key_file = cert_dir / "localhost.key"
    
    # Skip if certificate already exists
    if cert_file.exists() and key_file.exists():
        return
    
    # Ensure certs directory exists
    cert_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate self-signed certificate using openssl
    # Valid for 365 days, RSA 2048-bit, for localhost
    cmd = [
        "openssl", "req", "-x509", "-nodes",
        "-newkey", "rsa:2048",
        "-keyout", str(key_file),
        "-out", str(cert_file),
        "-days", "365",
        "-subj", "/CN=localhost/O=Airpod Local/C=US"
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Failed to generate self-signed certificate: {exc.stderr}") from exc
    except FileNotFoundError:
        raise RuntimeError("openssl not found - please install openssl to generate certificates")
