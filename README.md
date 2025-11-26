# airpod

A rich CLI tool for easily orchestrating popular AI services locally in a portable manner with GPU-awareness.

## Features

- Self-contained: all data stays in the project folder
- GPU detection with automatic passthrough to containers
- Rich terminal output with status tables and spinners

Easily spinup the following services:

- **Ollama** – Run LLMs locally (GGUF models supported)
- **Open WebUI** – Chat interface connected to Ollama

## Requirements

- Podman (with podman-compose)
- Python 3.10+
- NVIDIA GPU drivers (optional)

## Install

```bash
# Create venv and install
uv venv && uv pip install -e .

# Activate to use airpod command
source .venv/bin/activate
```

## Usage

```bash
airpod init       # Verify environment, create dirs, pull images
airpod start      # Start all services (alias: up)
airpod status     # Show service status (alias: ps)
airpod logs       # View logs
airpod stop       # Stop services (alias: down)
```

Run `airpod --help` for all options.

## License

See [LICENSE](./LICENSE).
