from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class ServiceSpec:
    name: str
    pod: str
    container: str
    image: str
    ports: List[Tuple[int, int]] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    volumes: List[Tuple[str, str]] = field(default_factory=list)  # host volume name -> container path
    needs_gpu: bool = False


OLLAMA_VOLUME = "aipod_ollama_data"
OPENWEBUI_VOLUME = "aipod_webui_data"

SERVICES: Dict[str, ServiceSpec] = {
    "ollama": ServiceSpec(
        name="ollama",
        pod="aipod-ollama",
        container="aipod-ollama-0",
        image="ollama/ollama:latest",
        ports=[(11434, 11434)],
        env={
            "OLLAMA_ORIGINS": "*",
            "OLLAMA_HOST": "0.0.0.0",
        },
        volumes=[(OLLAMA_VOLUME, "/root/.ollama")],
        needs_gpu=True,
    ),
    "open-webui": ServiceSpec(
        name="open-webui",
        pod="aipod-open-webui",
        container="aipod-open-webui-0",
        image="ghcr.io/open-webui/open-webui:latest",
        ports=[(3000, 3000)],
        env={
            "OLLAMA_BASE_URL": "http://host.containers.internal:11434",
        },
        volumes=[(OPENWEBUI_VOLUME, "/app/backend/data")],
    ),
}


def list_service_names() -> List[str]:
    return list(SERVICES.keys())


def get_service(name: str) -> Optional[ServiceSpec]:
    return SERVICES.get(name)
