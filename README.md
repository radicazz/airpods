# airpods

[![Tests](https://github.com/radicazz/airpods/actions/workflows/test.yml/badge.svg)](https://github.com/radicazz/airpods/actions/workflows/test.yml) [![Coverage](https://codecov.io/gh/radicazz/airpods/graph/badge.svg)](https://codecov.io/gh/radicazz/airpods)

User-friendly CLI for orchestrating local AI services with Podman.

## Prerequisites

- `uv`: Python environment & dependency manager
- `podman` & `podman-compose`: Container runtime
- *(optional)* `nvidia-smi`: GPU support

## Installation

```bash
git clone https://github.com/radicazz/airpods.git && cd airpods

# Local (project folder) installation
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
```

Run `airpods --help` for all available commands and options.

## License

Check out [LICENSE](./LICENSE) for more details.
