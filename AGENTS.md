# Agents & Plan

## Intent
Provide a Rich + Typer-powered CLI (`airpods/cli.py`, installed as the `airpods` command via uv tools) that orchestrates local AI services via Podman. Initial services: Ollama (GGUF-capable) and Open WebUI wired to Ollama. Future additions: ComfyUI and others.

## Command Surface
- Global options: `-v/--version` prints the CLI version; `-h/--help` shows the custom help view plus alias table.
- `init`: Verify dependencies (podman, podman-compose, uv, optional nvidia-smi), create volumes, pull images, summarize readiness.
- `start [service...]`: Ensure volumes/images, then launch pods (default both). GPU auto-detected and attached to Ollama; CPU fallback allowed. Exposed aliases: `up`.
- `stop [service...]`: Graceful stop; optional removal of pods while preserving volumes by default. Exposed aliases: `down`.
- `status [service...]`: Rich table showing pod/container state, ports, uptime, and an HTTP ping per service. Exposed aliases: `ps`.
- `logs [service...]`: Tail logs for specified services or all; supports follow/since/lines.
- `alias`: Rich table showing the canonical commands alongside their shorthand aliases.
- Optional `doctor`: Re-run checks without creating resources (not yet implemented).

## Architecture Notes
- Modules: `airpods/cli.py` (Typer entry + wiring, help/alias rendering), `airpods/podman.py` (subprocess wrapper), `airpods/system.py` (env checks, GPU detection), `airpods/config.py` (service specs), `airpods/logging.py` (Rich console themes), `airpods/ui.py` (Rich tables/panels), `podcli` (uv/python wrapper script).
- Pod specs include names, images, ports, env, volumes, and GPU requirements. Easy to extend mapping in `config.py` for new services.
- Errors surfaced with clear remediation (install Podman, start podman machine, check GPU drivers).

## Data & Images
- Volumes: `airpods_ollama_data` for models, `airpods_webui_data` for Open WebUI data.
- Images: `docker.io/ollama/ollama:latest`, `ghcr.io/open-webui/open-webui:latest`; pulled during `init`/`start`.
- Secrets: Open WebUI secret persisted at `~/.config/airpods/webui_secret` (or `$XDG_CONFIG_HOME/airpods/webui_secret`) during `init`, injected on start.
- Networking: Open WebUI targets Ollama via host-published `http://host.containers.internal:11434`.
- Secrets: Open WebUI `WEBUI_SECRET_KEY` generated and stored at `~/.config/airpods/webui_secret` (or `$XDG_CONFIG_HOME/airpods`).

## Testing Approach
- Unit tests mock subprocess interactions to validate command flow and flags.
- Integration (later): optional Podman-in-Podman smoke tests; GPU checks skipped when unavailable.
