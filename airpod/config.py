from __future__ import annotations

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


# Project structure - all data is local and portable
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
VOLUMES_DIR = PROJECT_ROOT / "volumes"
DATA_OLLAMA = VOLUMES_DIR / "data-ollama"
DATA_OPENWEBUI = VOLUMES_DIR / "data-open-webui"
DATA_SHARED = VOLUMES_DIR / "shared"
CONFIG_DIR = PROJECT_ROOT / "config"

# Volume paths (absolute paths for bind mounts)
OLLAMA_VOLUME = str(DATA_OLLAMA)
OPENWEBUI_VOLUME = str(DATA_OPENWEBUI)

SERVICES: Dict[str, ServiceSpec] = {
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
