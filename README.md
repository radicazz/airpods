# airpods

[![Version](https://img.shields.io/github/v/release/radicazz/airpods?color=blue)](https://github.com/radicazz/airpods/releases) [![Tests](https://github.com/radicazz/airpods/actions/workflows/test.yml/badge.svg)](https://github.com/radicazz/airpods/actions/workflows/test.yml) [![Coverage](https://codecov.io/gh/radicazz/airpods/graph/badge.svg)](https://codecov.io/gh/radicazz/airpods)

Effortlessly orchestrate _free & open-source_ AI services from the command-line.

## Features

Here's a few important features:

- Simple command-line interface
- NVIDIA GPU support (with multiple CUDA versions available)
- Highly configurable through `toml` configs
- Easily download ComfyUI & Ollama models from the CLI
- Config-driven ComfyUI custom nodes (git or local path) with auto-installed requirements
- Supports `Docker` & `Podman`

The following services are currently supported:

- [Ollama](https://github.com/ollama/ollama) - Language & Vision models for text, coding, tooling and more.
- [Llama](https://github.com/ggml-org/llama.cpp) - Lightweight C/C++ LLM inference with GGUF model support.
- [Open WebUI](https://github.com/open-webui/open-webui) - Feature-packed front-end chat with multi-model support.
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI) - Mature node-based UI for image generation workflows.

## Example

```bash
airpods start                       # Run all enabled services
airpods start ollama open-webui     # Run specific services

airpods status                      # Show service status and health
airpods logs ollama                 # View ollama's latest logs

airpods stop                        # Stop all running services
airpods stop comfyui                # Only stop ComfyUI (if running)
```

Run `airpods --help` for all available commands and options.

## Get Started

### Requirements

- [`uv`](https://docs.astral.sh/uv/getting-started/installation/): Install, upgrade & manage `airpods`
- Container Runtime (one of the following):
  - `podman` (recommended)
  - `docker`

> [!NOTE]
> AirPods automatically detects which container runtime is available. If both are installed, Podman is preferred by default. You can explicitly choose a runtime by setting `runtime.prefer` in your config file.

### Installation

Install `airpods` with `uv` from [Releases](https://github.com/radicazz/airpods/releases) or:

```bash
# This is the nightly installation.
uv tool install "git+https://github.com/radicazz/airpods.git@main"
```

> [!IMPORTANT]
> Upgrade your installation with `uv tool upgrade airpods` when a new version is available.

## Documentation

- [Configuration and state paths](docs/commands/config.md)
- [Ollama models](docs/commands/models.md)
- [GGUF downloads and search](docs/commands/gguf.md)
- [llama.cpp setup](docs/services/llamacpp.md)
- [ComfyUI setup](docs/services/comfyui.md) and [workflow/model sync](docs/commands/workflows.md)
- [Backups, restore, and cleanup](docs/commands/state.md)
- [GPU/CUDA selection](docs/configuration/cuda-detection.md) and [concurrent image pulls](docs/configuration/concurrent-pulls.md)
- [Open WebUI plugins](plugins/open-webui/README.md) and [ComfyUI nodes](plugins/comfyui/README.md)
- [Project goals](docs/goals.md), [roadmap](TODO.md), and [development workflow](AGENTS.md)

All services use host networking. The default UI URLs are `http://localhost:3000` (Open WebUI) and `http://localhost:8188` (ComfyUI); backend ports are 11434 (Ollama) and 11435 (llama.cpp). Set `services.open-webui.auto_configure_ollama = true` to inject Ollama connection settings, or configure connections in WebUI.

Use `airpods start --wait` to wait for readiness, `--cpu` to force CPU execution, and `--pre-fetch` to download missing images ahead of time. Startup may offer model/image downloads; `--yes` accepts those prompts. `airpods doctor` reports runtime and GPU setup issues.

## Development

```bash
uv sync --all-extras
uv run pytest
uv run pre-commit run --all-files
```

Run `uv sync --all-extras` first: a bare `uv run pytest` in a fresh checkout can fail with `ModuleNotFoundError: No module named 'typer'` because the dev extras and dependencies are not installed yet.

See [AGENTS.md](AGENTS.md) for versioning and commit conventions.

## License

Check out [LICENSE](./LICENSE) for more details.
