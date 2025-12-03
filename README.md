# airpods

User-friendly CLI for orchestrating local AI services with ease.

## Features

- One-command setup and start: `uv tool install --from . airpods` then `airpods init` / `airpods start`.
- GPU-aware: detect NVIDIA GPUs and attach to pods when available; gracefully fall back to CPU.
- Opinionated but extensible: defaults for ports/volumes/images, easy to extend with future services like ComfyUI.
- Helpful output: unified Rich/Typer experience with consistent tables, panels, and remediation hints across every command.
- Self-service diagnostics: `airpods doctor` audits your environment without touching pods or volumes.

## Getting Started

You will need the following before you get started:

- `uv`: Manages the Python environment & dependencies.
- `podman`: Containerized runtime for the AI services.
- `podman-compose`: Required for wiring multiple containers together.
- *(optional)* `nvidia-smi` + NVIDIA drivers: unlock GPU acceleration when available.

Installing the CLI:

```bash
git clone https://github.com/radicazz/airpods.git
cd airpods

uv venv && source .venv/bin/activate
uv pip install -e .
```

> [!NOTE]
> Use `uv tool install --from . airpods` to install the tool globally!

Use the CLI:

```bash
# Create & run the services
airpods init
airpods start

# Make sure everything is going well
airpods status

# Stop everything when you're done
airpods stop
```

Feel free to run `airpods --help` to see a full list of available commands.

## License

Check out [LICENSE](./LICENSE) for more details.
