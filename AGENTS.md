# Agents & Plan

## Intent
Provide a Rich + Typer-powered CLI (`airpod.py`) that orchestrates local AI services via Podman. Initial services: Ollama (GGUF-capable) and Open WebUI wired to Ollama. Future additions: ComfyUI and others.

## Command Surface (planned)
- `init`: Verify dependencies (podman, podman-compose, uv, optional nvidia-smi), create volumes, pull images, summarize readiness.
- `start [service...]`: Ensure volumes/images, then launch pods (default both). GPU auto-detected and attached to Ollama; CPU fallback allowed.
- `stop [service...]`: Graceful stop; optional removal of pods while preserving volumes by default.
- `status [service...]`: Rich table showing pod/container state, ports, uptime, and an HTTP ping per service.
- `logs [service...]`: Tail logs for specified services or all; supports follow/since/lines.
- Optional `doctor`: Re-run checks without creating resources.

## Architecture Notes
- Modules: `airpod.py` (Typer entry + wiring), `airpod/podman.py` (subprocess wrapper), `airpod/system.py` (env checks, GPU detection), `airpod/config.py` (service specs), `airpod/logging.py` (Rich console), `podcli` (uv/python wrapper script).
- Pod specs include names, images, ports, env, volumes, and GPU requirements. Easy to extend mapping in `config.py` for new services.
- Errors surfaced with clear remediation (install Podman, start podman machine, check GPU drivers).

## Data & Images
- **Self-Contained Storage**: All data lives in local directories within the project folder for portability:
  - `./volumes/data-ollama/` → Ollama models and data (bind mount to `/root/.ollama`)
  - `./volumes/data-open-webui/` → Open WebUI database and uploads (bind mount to `/app/backend/data`)
  - `./volumes/shared/` → Reserved for future shared storage needs
  - `./config/webui_secret` → Open WebUI session secret (local to project)
- **No Named Volumes**: Using bind mounts instead of Podman named volumes for transparency and portability
- Images: `docker.io/ollama/ollama:latest`, `ghcr.io/open-webui/open-webui:latest`; pulled during `init`/`start`
- Networking: Open WebUI targets Ollama via host-published `http://host.containers.internal:11434`
- Permissions: Directories created with 0755; Podman rootless mode handles UID mapping automatically

## Testing Approach
- Unit tests mock subprocess interactions to validate command flow and flags.
- Integration (later): optional Podman-in-Podman smoke tests; GPU checks skipped when unavailable.
