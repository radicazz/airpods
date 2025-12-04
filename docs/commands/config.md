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
Creates a default configuration file at `$AIRPODS_HOME/config.toml` (or `~/.config/airpods/config.toml`).

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
2. `$AIRPODS_HOME/config.toml`
3. `<repo_root>/config.toml`
4. `$XDG_CONFIG_HOME/airpods/config.toml`
5. `~/.config/airpods/config.toml`
6. Built-in defaults

## Template Variables

Configuration values support template expansion:

```toml
[services.open-webui.env]
OLLAMA_BASE_URL = "http://{{runtime.host_gateway}}:{{services.ollama.ports.0.host}}"
```

Available variables:
- `runtime.host_gateway`: Host gateway address
- `runtime.network_name`: Network name
- `services.<name>.ports.0.host`: Service host port
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
auto_confirm = false
debug = false

[dependencies]
required = ["podman", "podman-compose", "uv"]
optional = ["nvidia-smi"]
skip_checks = false

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
OLLAMA_BASE_URL = "http://ollama:11434"  # clean vs {{runtime.host_gateway}}:{{...}}
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
