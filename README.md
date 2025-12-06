# airpods

[![Tests](https://github.com/radicazz/airpods/actions/workflows/test.yml/badge.svg)](https://github.com/radicazz/airpods/actions/workflows/test.yml)

User-friendly CLI for orchestrating local AI services with Podman. The project currently supports the following services:

- [Ollama]() - GGUF-capable LLM inference engine
- [Open WebUI]() - Modern web interface for LLMs
- [ComfyUI]() - Node-based Stable Diffusion workflow
- [Gateway]() - Optional Caddy reverse proxy with unified authentication

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

### Optional: Enable Gateway for Unified Auth

The gateway service provides single sign-on authentication via Caddy:

```bash
# Enable gateway in config
echo '[services.gateway]
enabled = true' >> ~/.config/airpods/configs/config.toml

# Start with gateway
airpods start

# Access via gateway at http://localhost:8080
# Open WebUI authentication applies to all requests
```

**Benefits**: Network isolation, no credential duplication, multi-user support.  
**See**: `docs/commands/start.md#gateway-service` for details.

Run `airpods --help` for all available commands and options.

## License

Check out [LICENSE](./LICENSE) for more details.
