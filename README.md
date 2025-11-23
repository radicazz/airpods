# aipod

Rich, user-friendly CLI for orchestrating local AI services with Podman and UV. The initial focus is running Ollama (GGUF-capable) and Open WebUI in pods with sane defaults and simple lifecycle commands.

## Goals
- One-command setup and start: `uv run aipod.py init` and `uv run aipod.py start`.
- GPU-aware: detect NVIDIA GPUs and attach to pods when available; gracefully fall back to CPU.
- Opinionated but extensible: defaults for ports/volumes/images, easy to extend with future services like ComfyUI.
- Helpful output: Rich-powered status tables, clear errors, and direct pointers to next steps.

## Quickstart (planned)
1. Install prerequisites: Podman, Podman Compose (optional), UV, NVIDIA drivers (if GPU).
2. `uv run aipod.py init` to verify tools, create volumes, and pre-pull images.
3. `uv run aipod.py start` to launch Ollama + Open WebUI pods.
4. `uv run aipod.py status` to view health and ports; `uv run aipod.py logs` to inspect.

## Commands (current scaffold)
- `init` — checks dependencies, ensures volumes, and pulls images.
- `start [service...]` — starts pods (default both); GPU auto-detected unless `--cpu`.
- `stop [service...]` — stops pods; `--remove` removes pods after stop.
- `status [service...]` — reports pod status, ports, and container counts.
- `logs [service...]` — tails logs; supports `--follow`, `--since`, `--lines`.
- `version` — prints CLI version.

## Roadmap
- Core commands: `init`, `start`, `stop`, `status`, `logs`.
- Service definitions: Ollama pod (GGUF-ready) and Open WebUI pod linked to Ollama.
- Future services: ComfyUI and more via modular pod definitions.
- Config overrides: user config for ports, images, GPU toggle.
- Tests: subprocess mocks for Podman wrappers and command flows.
