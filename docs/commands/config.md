# docs/commands/config

The `airpods config` command manages your airpods configuration file.

## Quick Start

```bash
# Create default configuration
airpods config init

# View current config
airpods config show

# Edit in your $EDITOR
airpods config edit
```

## Commands

### `airpods config init`
Creates a default configuration file at `$AIRPODS_HOME/configs/config.toml` (or `~/.config/airpods/configs/config.toml`).

**Options:**
- `--force` / `-f`: Overwrite existing file

### `airpods config show`
Display the current configuration.

**Options:**
- `--format` / `-f`: Output format (`toml` or `json`)

### `airpods config path`
Show the location of the configuration file.

### `airpods config edit`
Open the configuration file in your `$EDITOR` (defaults to `nano`).

### `airpods config validate`
Check if the configuration is valid and show warnings.

### `airpods config reset`
Reset configuration to defaults. Creates a timestamped backup.

**Options:**
- `--force` / `-f`: Skip confirmation prompt

### `airpods config get <key>`
Print a specific configuration value using dot notation.

**Example:**
```bash
airpods config get cli.stop_timeout
airpods config get services.ollama.image
```

### `airpods config set <key> <value>`
Update a specific configuration value with validation.

**Options:**
- `--type` / `-t`: Value type (`auto`, `str`, `int`, `float`, `bool`, `json`)

**Examples:**
```bash
airpods config set cli.stop_timeout 30 --type int
airpods config set services.ollama.gpu.enabled false --type bool
```

## Configuration Priority

Airpods searches for configuration in this order:
1. `$AIRPODS_CONFIG` (environment variable)
2. `$AIRPODS_HOME/configs/config.toml`
3. `$AIRPODS_HOME/config.toml` (legacy location)
4. `<repo_root>/configs/config.toml`
5. `<repo_root>/config.toml` (legacy location)
6. `$XDG_CONFIG_HOME/airpods/configs/config.toml`
7. `$XDG_CONFIG_HOME/airpods/config.toml` (legacy location)
8. `~/.config/airpods/configs/config.toml`
9. `~/.config/airpods/config.toml` (legacy location)
10. Built-in defaults

**Note:** All airpods configuration files (including `config.toml` and `webui_secret`) are now stored in the `configs/` subdirectory for better organization. Legacy locations are still supported for backwards compatibility.

> [!TIP]
> `airpods start` (with or without `--pre-fetch`) automatically bootstraps the default `config.toml` at the first writable path in the list above and reloads the CLI so the new file is in effect immediately. Whichever directory hosts that config becomes the Airpods “home”: the CLI stores `configs/`, `volumes/`, webui secrets, and other runtime data alongside each other under that directory so everything stays grouped together.

## Template Variables

Configuration values support template expansion:

```toml
[services.open-webui.env]
OLLAMA_BASE_URL = "http://ollama:{{services.ollama.ports.0.container}}"
```

Available variables:
- `runtime.host_gateway`: Host gateway address
- `runtime.network_name`: Network name
- `services.<name>.ports.0.host`: Service host port
- `services.<name>.ports.0.container`: Service container port
- `services.<name>.image`: Service image
- `services.<name>.pod`: Service pod name

## Configuration Structure

```toml
[meta]
version = "1.0"

[runtime]
prefer = "auto"  # auto, podman, docker (docker not yet supported)
host_gateway = "auto"
network_name = "airpods_network"
gpu_device_flag = "auto"
restart_policy = "unless-stopped"

[runtime.network]
driver = "bridge"
subnet = "10.89.0.0/16"  # optional custom subnet
gateway = "10.89.0.1"    # optional custom gateway
dns_servers = ["8.8.8.8", "1.1.1.1"]  # optional custom DNS
ipv6 = false
internal = false

[cli]
stop_timeout = 10
log_lines = 200
ping_timeout = 2.0
startup_timeout = 120
startup_check_interval = 2.0
max_concurrent_pulls = 3
auto_confirm = false
verbose = false
debug = false

`startup_timeout` / `startup_check_interval` govern how long `airpods start` waits for each service to go healthy, and `max_concurrent_pulls` controls how many images Podman will pull in parallel (use `--sequential` to temporarily override). Set `auto_confirm` to true for unattended workflows where you want `clean` to skip prompts, and `verbose` when you want lifecycle commands to always show resource reuse messages even without `-v/--verbose`.

[dependencies]
required = ["podman", "podman-compose", "uv"]
optional = ["nvidia-smi"]
skip_checks = false

`skip_checks` lets airpods skip dependency probing entirely. This can be useful inside tightly controlled environments (CI, air-gapped towers) where you already know Podman, UV, and optional binaries are present and fast startup is preferred over repeated checks.

[services.ollama]
enabled = true
image = "docker.io/ollama/ollama:latest"
pod = "ollama"
container = "ollama-0"
network_aliases = ["ollama"]  # accessible at ollama:11434
needs_webui_secret = false

[[services.ollama.ports]]
host = 11434
container = 11434

[services.ollama.gpu]
enabled = true
force_cpu = false

Set `force_cpu` when a service should never request GPU resources even if they are globally available. This makes it possible to disable GPU scheduling for individual services via configuration while still letting operators pass `airpods start --cpu` to force a CLI-wide CPU fallback.

[services.ollama.health]
path = "/api/tags"
expected_status = [200, 299]

[services.ollama.env]
OLLAMA_ORIGINS = "*"
OLLAMA_HOST = "0.0.0.0"
```

## Network Configuration

Services can use network aliases for cleaner inter-service communication:

```toml
[services.ollama]
network_aliases = ["ollama"]

[services.open-webui.env]
OLLAMA_BASE_URL = "http://ollama:11434"  # prefer aliases; host gateway only for host-bound clients
```

**Network options** (`runtime.network`):
- `driver`: Network driver (default: `"bridge"`)
- `subnet`: Custom subnet in CIDR format (e.g., `"10.89.0.0/16"`)
- `gateway`: Custom gateway IP
- `dns_servers`: List of custom DNS servers
- `ipv6`: Enable IPv6 networking
- `internal`: Restrict external network access

**Connection methods:**
- Host port: `http://localhost:11434` (from host machine)
- Network alias: `http://ollama:11434` (from containers, recommended)
- Host gateway: `http://host.containers.internal:11434` (from containers)

## Tips

- Use `airpods config validate` after manual edits
- The `needs_webui_secret` flag automatically injects the webui secret
- GPU detection is automatic; override with `gpu.force_cpu = true`
- Network aliases simplify service URLs and improve performance
- All changes are validated before saving

## Runtime Support

**Podman** (`runtime.prefer = "auto"` or `"podman"`):
- Fully supported and recommended
- Default container runtime for airpods
- Supports GPU passthrough and pod management

**Docker** (`runtime.prefer = "docker"`):
- Not yet supported in this release
- Setting this value will result in a clear error message: "Docker is not supported yet. Please set runtime.prefer back to 'podman' or 'auto' and try again."
- Docker support is planned for a future release
