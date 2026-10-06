"""Built-in default configuration for airpods."""

from __future__ import annotations

DEFAULT_CONFIG_DICT = {
    "meta": {
        "version": "1.0",
    },
    "runtime": {
        "prefer": "auto",
        "gpu_device_flag": "auto",
        "restart_policy": "unless-stopped",
        "cuda_version": "auto",
    },
    "cli": {
        "stop_timeout": 10,
        "log_lines": 200,
        "ping_timeout": 2.0,
        "startup_timeout": 120,
        "startup_check_interval": 2.0,
        "max_concurrent_pulls": 3,
        "plugin_owner": "auto",
        "auto_confirm": False,
        "debug": False,
    },
    "dependencies": {
        "required": ["uv"],
        "runtime_deps": {
            "podman": ["podman"],
            "docker": ["docker"],
        },
        "optional": ["nvidia-smi"],
        "skip_checks": False,
    },
    "services": {
        "ollama": {
            "enabled": True,
            "image": "docker.io/ollama/ollama:latest",
            "pod": "ollama",
            "container": "ollama-0",
            "ports": [{"host": 11434, "container": 11434}],
            "volumes": {
                "data": {
                    "source": "bind://airpods_ollama_data",
                    "target": "/root/.ollama",
                },
                "llamacpp_models": {
                    "source": "bind://airpods_models/gguf",
                    "target": "/airpods/llamacpp",
                },
            },
            "gpu": {"enabled": True, "force_cpu": False},
            "health": {"path": "/api/tags", "expected_status": [200, 299]},
            "env": {
                "OLLAMA_ORIGINS": "*",
                "OLLAMA_HOST": "0.0.0.0",
                "OLLAMA_DEBUG": "1",
            },
            "resources": {},
            "needs_webui_secret": False,
        },
        "open-webui": {
            "enabled": True,
            "image": "ghcr.io/open-webui/open-webui:latest",
            "pod": "open-webui",
            "container": "open-webui-0",
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
                # With host networking, container binds to PORT directly (no port mapping)
                "PORT": "{{services.open-webui.ports.0.host}}",
                "ENABLE_COMMUNITY_SHARING": "True",
            },
            "resources": {},
            "needs_webui_secret": True,
            "auto_configure_ollama": False,
        },
        "comfyui": {
            "enabled": True,
            "image": "docker.io/yanwk/comfyui-boot:cu128-slim",
            "pod": "comfyui",
            "container": "comfyui-0",
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
                "custom_nodes": {
                    "source": "bind://comfyui_custom_nodes",
                    "target": "/basedir/custom_nodes",
                },
            },
            "custom_nodes": {
                "install": [
                    {
                        "name": "comfyui-gguf",
                        "repo": "https://github.com/radicazz/comfyui-gguf",
                        "ref": "main",
                        "requirements": "requirements.txt",
                    }
                ]
            },
            "gpu": {"enabled": True, "force_cpu": False},
            "health": {"path": "/", "expected_status": [200, 299]},
            "env": {},
            "resources": {},
            "needs_webui_secret": False,
        },
        "llamacpp": {
            "enabled": True,
            "image": "ghcr.io/ggml-org/llama.cpp:server",
            "pod": "llamacpp",
            "container": "llamacpp-0",
            "ports": [{"host": 11435, "container": 8080}],
            "volumes": {
                "models": {
                    "source": "bind://airpods_models/gguf",
                    "target": "/models",
                },
                "ollama_models": {
                    "source": "bind://airpods_ollama_data",
                    "target": "/airpods/ollama",
                },
            },
            "gpu": {"enabled": True, "force_cpu": False},
            "health": {"path": "/health", "expected_status": [200, 299]},
            "env": {},
            "resources": {},
            "needs_webui_secret": False,
            "default_model": "granite-4.0-h-1b-Q4_K_M.gguf",
            "default_model_url": "https://huggingface.co/unsloth/granite-4.0-h-1b-GGUF/resolve/main/granite-4.0-h-1b-Q4_K_M.gguf",
            "command_args": {
                "model": "/models/{{services.llamacpp.default_model}}",
                "ctx_size": 4096,
                "n_gpu_layers": 40,
                "threads": 8,
                "port": "{{services.llamacpp.ports.0.host}}",
                "host": "0.0.0.0",
            },
        },
    },
}
