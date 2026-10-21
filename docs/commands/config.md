# docs/commands/config

Airpods deep-merges a TOML file with built-in defaults, validates it, then resolves templates. Use `airpods config show --format json` to inspect the effective settings.

## Commands

| Command                                  | Behavior                                                                                        |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `config init [--force]`                  | Write defaults to the active path, or `<state-root>/configs/config.toml`; `--force` overwrites. |
| `config show [--format FORMAT]`          | Display TOML or effective JSON configuration.                                                   |
| `config path`                            | Show the active file or default destination.                                                    |
| `config edit`                            | Open the file in `$EDITOR` (default `nano`); create defaults if needed.                         |
| `config validate`                        | Validate the configuration and report warnings.                                                 |
| `config reset [--force]`                 | Reset to defaults with a timestamped backup; `--force` skips confirmation.                      |
| `config get <key>`                       | Read a value using dot notation.                                                                |
| `config set <key> <value> [--type TYPE]` | Validate and save a value; types: `auto`, `str`, `int`, `float`, `bool`, `json`.                |

```bash
airpods config init
airpods config set runtime.prefer docker
airpods config set services.ollama.gpu.force_cpu true --type bool
airpods config get cli.startup_timeout
```

Help, version, and configuration repair commands (`init`, `edit`, `reset`) work without a container runtime or a valid active configuration.

## File Discovery and State Root

1. If `AIRPODS_CONFIG` is set, use that file exclusively. A missing file is an error when loading config; repair commands can create it.
2. Otherwise, if `AIRPODS_HOME` is set, check its `configs/config.toml`, then legacy `config.toml`. If neither exists, use defaults under that home; do not search other locations.
3. Otherwise, search `<repo-root>/configs/config.toml`, then `<repo-root>/config.toml` when a checkout is detected.
4. Then search `$XDG_CONFIG_HOME/airpods/configs/config.toml`, followed by its legacy `config.toml`, when XDG is set.
5. Then search `~/.config/airpods/configs/config.toml`, followed by its legacy `config.toml`.
6. Fall back to built-in defaults.

The selected file's parent is the state root, except that a parent named `configs` makes its parent the root. The active config can therefore override the state location implied by `AIRPODS_HOME`.

Without a config, the state root is explicit `AIRPODS_HOME`, otherwise `$XDG_CONFIG_HOME/airpods`, otherwise a writable detected checkout, otherwise `~/.config/airpods`. `start` (including `--pre-fetch`) can bootstrap defaults at `<state-root>/configs/config.toml`.

Runtime data lives under that root:

- `configs/`: configuration, `webui_secret`, and restore metadata.
- `volumes/`: bind-mounted service data; `bind://name/path` resolves here.
- `volumes/airpods_models/gguf/`: shared GGUF files for llama.cpp.

## Runtime and CLI Settings

This partial configuration overrides defaults; omitted services and fields remain enabled/configured as shipped. Generate a complete file with `config init`.

```toml
[runtime]
prefer = "auto"  # auto, podman, docker; auto prefers Podman
restart_policy = "unless-stopped"
gpu_device_flag = "auto"
cuda_version = "auto"  # auto, cu118, cu126, cu128, cu130, cpu
comfyui_provider = "auto"  # auto, yanwk, mmartial

[cli]
stop_timeout = 10
log_lines = 200
ping_timeout = 2.0
startup_timeout = 120
startup_check_interval = 2.0
max_concurrent_pulls = 3
plugin_owner = "auto"  # auto, admin, airpods
auto_confirm = false
verbose = false
debug = false

[dependencies]
required = ["uv"]
optional = ["nvidia-smi"]
skip_checks = false

[dependencies.runtime_deps]
podman = ["podman"]
docker = ["docker"]
```

`startup_timeout` and `startup_check_interval` control readiness polling with `start --wait`; failures/timeouts exit with status 1. `max_concurrent_pulls` accepts 1–10; `--sequential` overrides it. `auto_confirm` skips supported start/download/cleanup prompts. `skip_checks` bypasses dependency probing.

For WebUI plugin ownership, `auto` reuses an existing admin and otherwise uses `system`; `admin` follows the same resolution but warns when no admin exists. The legacy `airpods` mode warns and uses `system`. Airpods never creates an Open WebUI account or default password. See [plugin behavior](../../plugins/open-webui/README.md).

## Services, Networking, and Templates

Both runtimes use **host networking**. Containers share the host network and reach each other through `localhost`. `ports` records endpoint metadata; it does not forward ports. The service process must listen on the chosen host port (for example WebUI's `PORT` or llama.cpp's `command_args.port`). Bridge network settings and `network_aliases` are not supported.

```toml
[services.open-webui]
auto_configure_ollama = true

[services.ollama.gpu]
enabled = true
force_cpu = false

[services.ollama.resources]
memory = "8g"
cpus = "4"
```

`auto_configure_ollama` is off by default. When enabled, it injects Ollama URLs using Ollama's host port. To configure only the native Ollama URL explicitly instead:

```toml
[services.open-webui.env]
OLLAMA_BASE_URL = "http://localhost:{{services.ollama.ports.0.host}}"
```

Templates are resolved in service environment values, `default_model`, `default_model_url`, and command arguments. Available service references include `services.<name>.ports.0.host`, `.ports.0.container`, `.image`, `.pod`, and `.default_model`. Runtime fields from the schema can also be referenced; there is no `runtime.host_gateway` or `runtime.network_name` field.

Service fields also include `enabled`, `image`, `pod`, `container`, `volumes`, `health`, `pids_limit`, `needs_webui_secret`, `command_args`, and `entrypoint_override`. See [llama.cpp](../services/llamacpp.md) for command arguments and [CUDA selection](../configuration/cuda-detection.md) for CPU/GPU settings. Validate manual edits with `airpods config validate`.

## ComfyUI Custom Nodes

```toml
[services.comfyui.custom_nodes]
install = [
  { name = "comfyui-gguf", repo = "https://github.com/radicazz/comfyui-gguf", ref = "main", requirements = "requirements.txt" },
  { name = "local-node", path = "custom_nodes/local-node", requirements = "requirements.txt" }
]
```

Each entry must set exactly one of `repo` or `path`. Git sources require `git`; local paths must exist and relative paths resolve under the state root. Requirements default to `requirements.txt` and install inside the running container; set `requirements = ""` to skip them. See [ComfyUI](../services/comfyui.md) for usage and mounts.
