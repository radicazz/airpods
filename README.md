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

- [Ollama](https://github.com/ollama/ollama) - Language & Vision models for text, coding, tolling and more.
- [Llama](https://github.com/ggml-org/llama.cpp) - Lightweight C/C++ LLM inference with GGUF model support.
- [Open WebUI](https://github.com/open-webui/open-webui) - Feature-packed front-end chat with multi-model support.
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI) - Mature node-based UI for image generation workflows.

## Example

```bash
airpods start                       # Runs all available services
airpods start ollama open-webui     # Run specific services

airpods status                      # Get the status of every running service
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
# This is the nighly installation.
uv tool install "git+https://github.com/radicazz/airpods.git@main"
```

> [!IMPORTANT]
> Upgrade your installation with `uv tool upgrade airpods` when a new version is available.

## License

Check out [LICENSE](./LICENSE) for more details.
