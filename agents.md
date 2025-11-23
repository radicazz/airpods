# Agents & Plan

## Intent
Provide a Rich + Typer-powered CLI (`aipod.py`) that orchestrates local AI services via Podman. Initial services: Ollama (GGUF-capable) and Open WebUI wired to Ollama. Future additions: ComfyUI and others.

## Command Surface (planned)
- `init`: Verify dependencies (podman, podman-compose, uv, optional nvidia-smi), create volumes, pull images, summarize readiness.
- `start [service...]`: Ensure volumes/images, then launch pods (default both). GPU auto-detected and attached to Ollama; CPU fallback allowed.
- `stop [service...]`: Graceful stop; optional removal of pods while preserving volumes by default.
- `status [service...]`: Rich table showing pod/container state, ports, uptime, and an HTTP ping per service.
- `logs [service...]`: Tail logs for specified services or all; supports follow/since/lines.
- Optional `doctor`: Re-run checks without creating resources.

## Architecture Notes
- Modules: `aipod.py` (Typer entry + wiring), `aipod/podman.py` (subprocess wrapper), `aipod/system.py` (env checks, GPU detection), `aipod/config.py` (service specs), `aipod/logging.py` (Rich console), `podcli` (uv/python wrapper script).
- Pod specs include names, images, ports, env, volumes, and GPU requirements. Easy to extend mapping in `config.py` for new services.
- Errors surfaced with clear remediation (install Podman, start podman machine, check GPU drivers).

## Data & Images
- Volumes: `aipod_ollama_data` for models, `aipod_webui_data` for Open WebUI data.
- Images: `docker.io/ollama/ollama:latest`, `ghcr.io/open-webui/open-webui:latest`; pulled during `init`/`start`.
- Secrets: Open WebUI secret persisted at `~/.config/aipod/webui_secret` (or `$XDG_CONFIG_HOME/aipod/webui_secret`) during `init`, injected on start.
- Networking: Open WebUI targets Ollama via host-published `http://host.containers.internal:11434`.
- Secrets: Open WebUI `WEBUI_SECRET_KEY` generated and stored at `~/.config/aipod/webui_secret` (or `$XDG_CONFIG_HOME/aipod`).

## Testing Approach
- Unit tests mock subprocess interactions to validate command flow and flags.
- Integration (later): optional Podman-in-Podman smoke tests; GPU checks skipped when unavailable.
