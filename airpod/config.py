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
    is_infrastructure: bool = False


# Project structure - all data is local and portable
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
VOLUMES_DIR = PROJECT_ROOT / "volumes"
DATA_OLLAMA = VOLUMES_DIR / "data-ollama"
DATA_OPENWEBUI = VOLUMES_DIR / "data-open-webui"
DATA_SHARED = VOLUMES_DIR / "shared"
DATA_CADDY = VOLUMES_DIR / "caddy-data"
CONFIG_DIR = PROJECT_ROOT / "config"
CADDY_CONFIG = str(CONFIG_DIR)
CADDY_DATA = str(DATA_CADDY)

# Volume paths (absolute paths for bind mounts)
OLLAMA_VOLUME = str(DATA_OLLAMA)
OPENWEBUI_VOLUME = str(DATA_OPENWEBUI)

SERVICES: Dict[str, ServiceSpec] = {
    "caddy": ServiceSpec(
        name="caddy",
        pod="airpod-caddy",
        container="airpod-caddy-0",
        image="docker.io/library/caddy:2-alpine",
        ports=[(8443, 8443), (8080, 8080)],
        env={},
        volumes=[(CADDY_CONFIG, "/etc/caddy"), (CADDY_DATA, "/data")],
        needs_gpu=False,
        health_path="/",
        is_infrastructure=True,
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
}


def list_service_names() -> List[str]:
    return list(SERVICES.keys())


def get_service(name: str) -> Optional[ServiceSpec]:
    return SERVICES.get(name)


def ensure_caddyfile() -> None:
    """Generate Caddyfile from template if it doesn't exist."""
    caddyfile_path = CONFIG_DIR / "Caddyfile"
    template_path = CONFIG_DIR / "Caddyfile.template"
    
    if caddyfile_path.exists():
        return
    
    if not template_path.exists():
        raise RuntimeError(f"Caddyfile template not found at {template_path}")
    
    # Copy template to Caddyfile
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
