# airpods

[![Tests](https://github.com/radicazz/airpods/actions/workflows/test.yml/badge.svg)](https://github.com/radicazz/airpods/actions/workflows/test.yml)

User-friendly CLI for orchestrating local AI services with Podman. The project currently supports the following services:

- [Ollama]()
- [Open WebUI]()
- [ComfyUI]()

## Prerequisites

- `uv`: Python environment & dependency manager
- `podman` & `podman-compose`: Container runtime
- *(optional)* `nvidia-smi`: GPU support

## Installation

```bash
# Development setup
git clone https://github.com/radicazz/airpods.git && cd airpods
uv venv && source .venv/bin/activate
uv pip install -e . '.[dev]'

# Global installation
uv tool install --from . airpods
```

## Quick Start

```bash
# Prefetch images & create volumes
airpods start --init

# Start services
airpods start

# Check status
airpods status

# Stop services
airpods stop

# Clean up everything
airpods clean --all
```

Run `airpods --help` for all available commands and options.

## License

Check out [LICENSE](./LICENSE) for more details.
