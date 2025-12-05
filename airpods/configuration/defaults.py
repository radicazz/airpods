"""Built-in default configuration for airpods."""

from __future__ import annotations

DEFAULT_CONFIG_DICT = {
    "meta": {
        "version": "1.0",
    },
    "runtime": {
        "prefer": "auto",
        "host_gateway": "auto",
        "network_name": "airpods_network",
        "network": {
            "driver": "bridge",
            "dns_servers": [],
            "ipv6": False,
            "internal": False,
        },
        "gpu_device_flag": "auto",
        "restart_policy": "unless-stopped",
    },
    "cli": {
        "stop_timeout": 10,
        "log_lines": 200,
        "ping_timeout": 2.0,
        "auto_confirm": False,
        "debug": False,
    },
    "dependencies": {
        "required": ["podman", "podman-compose", "uv"],
        "optional": ["nvidia-smi"],
        "skip_checks": False,
    },
    "services": {
        "ollama": {
            "enabled": True,
            "image": "docker.io/ollama/ollama:latest",
            "pod": "ollama",
            "container": "ollama-0",
            "network_aliases": ["ollama"],
            "ports": [{"host": 11434, "container": 11434}],
            "volumes": {
                "data": {
                    "source": "bind://airpods_ollama_data",
                    "target": "/root/.ollama",
                }
            },
            "gpu": {"enabled": True, "force_cpu": False},
            "health": {"path": "/api/tags", "expected_status": [200, 299]},
            "env": {
                "OLLAMA_ORIGINS": "*",
                "OLLAMA_HOST": "0.0.0.0",
            },
            "resources": {},
            "needs_webui_secret": False,
        },
        "open-webui": {
            "enabled": True,
            "image": "ghcr.io/open-webui/open-webui:latest",
            "pod": "open-webui",
            "container": "open-webui-0",
            "network_aliases": ["webui", "open-webui"],
            "ports": [{"host": 3000, "container": 8080}],
            "volumes": {
                "data": {
                    "source": "bind://airpods_webui_data",
                    "target": "/app/backend/data",
                },
                "plugins": {
                    "source": "bind://webui_plugins",
                    "target": "/app/backend/data/functions",
                },
            },
            "gpu": {"enabled": False, "force_cpu": False},
            "health": {"path": "/", "expected_status": [200, 399]},
            "env": {
                "OLLAMA_BASE_URL": "http://ollama:{{services.ollama.ports.0.container}}",
                "ENABLE_COMMUNITY_SHARING": "True",
            },
            "resources": {},
            "needs_webui_secret": True,
        },
        "comfyui": {
            "enabled": True,
            "image": "docker.io/yanwk/comfyui-boot:cu128-slim",
            "pod": "comfyui",
            "container": "comfyui-0",
            "network_aliases": ["comfyui"],
            "ports": [{"host": 8188, "container": 8188}],
            "volumes": {
                "workspace": {
                    "source": "bind://comfyui/workspace",
                    "target": "/workspace",
                },
                "models": {
                    "source": "bind://airpods_comfyui_data",
                    "target": "/root/ComfyUI/models",
                },
            },
            "gpu": {"enabled": True, "force_cpu": False},
            "health": {"path": "/", "expected_status": [200, 299]},
            "env": {},
            "resources": {},
            "needs_webui_secret": False,
        },
    },
}
