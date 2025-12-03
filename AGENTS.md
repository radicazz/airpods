# Agents & Plan

## Intent
Provide a Rich + Typer-powered CLI (packaged under `airpods/cli/`, installed as the `airpods` command via uv tools) that orchestrates local AI services via Podman. Initial services: Ollama (GGUF-capable) and Open WebUI wired to Ollama. Future additions: ComfyUI and others.

## Command Surface
- Global options: `-v/--version` prints the CLI version; `-h/--help` shows the custom help view plus alias table.
- `init`: Verify dependencies (podman, podman-compose, uv, optional nvidia-smi), create volumes, pull images, summarize readiness, and report whether each resource was created or already present.
- `start [service...]`: Ensure volumes/images, then launch pods (default both) while explaining when networks, volumes, pods, or containers are reused vs newly created. Prompts before replacing existing containers unless the user passes `--force`. GPU auto-detected and attached to Ollama; CPU fallback allowed. Exposed aliases: `up`.
- `stop [service...]`: Graceful stop; optional removal of pods while preserving volumes by default, with an interactive confirmation prompt before destructive removal. Exposed aliases: `down`.
- `status [service...]`: Rich table showing pod/container state, ports, uptime, and an HTTP ping per service. Exposed aliases: `ps`.
- `logs [service...]`: Tail logs for specified services or all; supports follow/since/lines.
- `doctor`: Re-run checks without creating resources; surfaces remediation hints without touching pods/volumes.

## Architecture Notes
- CLI package layout:
  - `airpods/cli/__init__.py` – creates the Typer app, registers commands, exposes legacy compatibility helpers.
  - `airpods/cli/common.py` – shared constants, service manager, and Podman/dependency helpers.
  - `airpods/cli/help.py` – Rich-powered help/alias rendering tables used by the root callback.
  - `airpods/cli/status_view.py` – status table + health probing utilities.
  - `airpods/cli/commands/` – individual command modules (`init`, `doctor`, `start`, `stop`, `status`, `logs`, `version`) each registering via `commands.__init__.register`.
  - `airpods/cli/type_defs.py` – shared Typer command mapping type alias.
- Supporting modules: `airpods/podman.py` (subprocess wrapper), `airpods/system.py` (env checks, GPU detection), `airpods/config.py` (service specs), `airpods/logging.py` (Rich console themes), `airpods/ui.py` (Rich tables/panels), `podcli` (uv/python wrapper script).
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

## Development Workflow
- Run `uv format` after code changes and before commits to maintain consistent formatting.
