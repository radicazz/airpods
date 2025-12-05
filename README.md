# airpods

[![Tests](https://github.com/radicazz/airpods/actions/workflows/test.yml/badge.svg)](https://github.com/radicazz/airpods/actions/workflows/test.yml)

User-friendly CLI for orchestrating local AI services with ease.

## Features

- One-command setup and start: `uv tool install --from . airpods` then `airpods start --init` (prefetch) / `airpods start`.
- GPU-aware: detect NVIDIA GPUs and attach to pods when available; gracefully fall back to CPU.
- Advanced networking: custom DNS names, network aliases, subnets, and DNS servers for flexible service discovery.
- Opinionated but extensible: defaults for ports/volumes/images, easy to extend with future services like ComfyUI.
- Helpful output: unified Rich/Typer experience with consistent tables, panels, and remediation hints across every command.
- Self-service diagnostics: `airpods doctor` audits your environment without touching pods or volumes.
- **Auto-import plugins**: Bundled Open WebUI plugins are automatically synced to the filesystem and imported into the database when starting the `open-webui` service.

## Getting Started

You will need the following before you get started:

- `uv`: Manages the Python environment & dependencies.
- `podman`: Containerized runtime for the AI services.
- `podman-compose`: Required for wiring multiple containers together.
- *(optional)* `nvidia-smi` + NVIDIA drivers: unlock GPU acceleration when available.

Install the CLI (this flow is intended for developers):

```bash
git clone https://github.com/radicazz/airpods.git
cd airpods

uv venv && source .venv/bin/activate
uv pip install -e . '.[dev]'
```

> [!NOTE]
> Use `uv tool install --from . airpods` to install the tool globally!

Use the CLI:

```bash
# Prefetch images/volumes without starting (optional)
airpods start --init

# Create & run the services
airpods start

# Make sure everything is going well
airpods status

# Stop everything when you're done
airpods stop

# Clean up when you're completely done (removes volumes, images, configs)
airpods clean --all
```

### Cleanup Options

The `clean` command offers granular control over what gets removed:

```bash
# Preview what would be deleted
airpods clean --all --dry-run

# Remove only volumes and bind mounts (keeps images and configs)
airpods clean --volumes

# Remove only images (free up disk space, ~10-20GB typically)
airpods clean --images

# Remove everything except configs (useful for fresh start with same settings)
airpods clean --pods --volumes --images --network

# Nuclear option: remove everything and skip confirmations
airpods clean --all --force
```

Feel free to run `airpods --help` to see a full list of available commands.

The first run of `airpods start --init` (or `airpods start`) writes a default configuration to `$AIRPODS_HOME/configs/config.toml` (defaults to `~/.config/airpods/configs/config.toml`) and reloads the CLI immediately so any tweaks you make take effect right away. Whatever directory hosts that config becomes the single home for Airpods data: the CLI creates sibling `volumes/`, `configs/`, and secret files there so everything (models, secrets, runtime state) stays grouped together.

## License

Check out [LICENSE](./LICENSE) for more details.
