# airpod

Rich, user-friendly CLI for orchestrating local AI services with Podman and Python (uv). The initial focus is running Ollama (GGUF-capable) and Open WebUI in pods with sane defaults and simple lifecycle commands.

## Features

- One-command setup and start: `uv run airpod.py init` and `uv run airpod.py start`.
- GPU-aware: detect NVIDIA GPUs and attach to pods when available; gracefully fall back to CPU.
- Opinionated but extensible: defaults for ports/volumes/images, easy to extend with future services like ComfyUI.
- Helpful output: Rich-powered status tables, clear errors, and direct pointers to next steps.

## Getting Started

Make sure you have the following:

- Podman (with podman-compose)
- Python (with uv)
- [optional] NVIDIA GPU Drivers

Then you setup your pods with the following:

```bash
# Verify environment, create volumes and pre-pull images
uv run airpod.py init

# Run the services
uv run airpod.py start

# Make sure everything is going well
uv run airpod.py status

# Stop everything when you're done
uv run airpod.py status
```

Feel free to run `uv run airpod.py -h ` to see a full list of available commands.

## Notes

Images are referenced with fully-qualified registries: `docker.io/ollama/ollama:latest` and `ghcr.io/open-webui/open-webui:latest`.

Security: `init` generates and persists an Open WebUI secret at `~/.config/airpod/webui_secret` (or `$XDG_CONFIG_HOME/airpod/webui_secret`) and injects it when starting the WebUI container.

Open WebUI is configured to talk to Ollama via `http://host.containers.internal:11434` (host-published port).
Networking: Open WebUI points at Ollama via `http://host.containers.internal:11434` (host-published port) to avoid cross-pod DNS issues.

## License

Check out [LICENSE](./LICENSE) for more details.

