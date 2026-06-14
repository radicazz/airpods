# Agents & Plan

## Intent
Provide a Rich + Typer-powered CLI (packaged under `airpods/cli/`, installed as the `airpods` command via uv tools) that orchestrates local AI services via container runtimes (Podman or Docker). Services are configurable via TOML files with template support. Services: Ollama, Open WebUI, ComfyUI (provider/CUDA selectable), and llama.cpp server (GGUF-capable).

## Command Surface
- Global options: `-v/--version` prints the CLI version; `-V/--verbose` enables detailed output; `-h/--help` shows the custom help view plus alias table.
- `start [service...]`: Ensures volumes/images, then launches pods (default: all enabled services) while explaining when volumes, pods, or containers are reused vs newly created. After pre-flight checks/validations (runtime, already-running detection, volumes, GPU/CUDA, llama model presence, etc.) shows a confirmation listing the services that will be started (skip with `--yes`). Also shows download confirmation with sizes and disk space checks (skip with `--yes`). When `--wait` is set, waits for each service to report healthy (HTTP ping when available) for up to `cli.startup_timeout` seconds, polling every `cli.startup_check_interval` seconds; services without HTTP health are treated as ready when their pod is running. Skips recreation if containers are already running. GPU auto-detected and attached when enabled; CPU fallback allowed. `--pre-fetch` downloads service images and exits without starting containers for ahead-of-time cache warmups. Service aliases: `comfy`/`comfyui`/`comfy-ui` → `comfyui`, `llama`/`llama-cpp`/`llama.cpp` → `llamacpp`. Exposed aliases: `up`, `run`.
- `stop [service...]`: Graceful stop; optional removal of pods while preserving volumes by default, with an interactive confirmation prompt before destructive removal. Exposed aliases: `down`.
- `status [service...]`: Compact Rich table (Service / Status / Info) summarizing HTTP health plus friendly URLs for running pods, or pod status + port summaries for stopped ones; redundant columns (pod name, uptime, counts) were removed for readability. Exposed aliases: `ps`, `info`.
- `logs [service...]`: Tail logs for specified services or all; supports follow/since/lines.
- `doctor`: Re-run checks without creating resources; surfaces remediation hints without touching pods/volumes.
- `models`: Manage Ollama models with subcommands:
  - `search <query>`: Search Ollama's registry for models by name/tag
  - `pull <model>`: Download a model to local Ollama instance
  - `list` (aliases: `ls`): Show installed models with sizes
  - `info <model>`: Show detailed information about an installed model
  - `remove <model>`: Delete a local model
- `workflows`: ComfyUI workflow and model utilities:
  - `add [source]`: Import workflow JSON files from local paths, URLs, or repo (plugins/comfyui/workflows). Auto-detects and copies companion TOML mapping files. When no source is specified, lists available workflows from repo. Supports `--sync` to automatically download models after import and `--overwrite` to replace existing workflows.
  - `list` (aliases: `ls`): List saved workflow JSON files with model info
  - `sync <workflow>`: Install missing models for a workflow
  - `pull <url>`: Download a single model file
  - `delete <workflow>` (alias): Remove a saved workflow JSON file (alias for `remove`)
  - `remove <workflow>`: Remove a saved workflow JSON file
  - `path`: Show workspace/workflows/models paths
  - `api`: Show API endpoints
- `state`: Manage local state with subcommands:
  - `backup`: Create compressed archive of configs, Open WebUI database, plugins, and Ollama metadata (not model binaries). Supports custom destination, filename, and optional SQL dump.
  - `restore <archive>`: Unpack backup archive and restore configs, WebUI data, and metadata. Backs up existing data first. Includes flags to skip configs/db/plugins/models.
  - `clean`: Remove volumes, images, configs, and user data created by airpods. Offers granular control via flags:
    - `--all/-a`: Remove everything (pods, volumes, images, configs)
    - `--pods/-p`: Stop and remove all pods and containers
    - `--volumes/-v`: Remove Podman volumes and bind mount directories
    - `--images/-i`: Remove pulled container images
    - `--configs/-c`: Remove config files (config.toml, webui_secret)
    - `--force/-f`: Skip confirmation prompts
    - `--dry-run`: Show what would be deleted without deleting
    - `--backup-config`: Backup config.toml before deletion (default: enabled)
- `config`: Manage configuration with subcommands:
  - `init`: Create default config file at `$AIRPODS_HOME/configs/config.toml`
  - `show`: Display current configuration (TOML or JSON format)
  - `path`: Show configuration file location
  - `edit`: Open config in `$EDITOR`
  - `validate`: Check configuration validity
  - `reset`: Reset to defaults with backup
  - `get <key>`: Print specific value using dot notation
  - `set <key> <value>`: Update specific value with validation

## Architecture Notes
- CLI package layout:
  - `airpods/cli/__init__.py` – creates the Typer app, registers commands, exposes legacy compatibility helpers.
  - `airpods/cli/common.py` – shared constants, service manager, and runtime/dependency helpers.
  - `airpods/cli/help.py` – Rich-powered help/alias rendering tables used by the root callback.
  - `airpods/cli/status_view.py` – status table + health probing utilities.
  - `airpods/cli/commands/` – individual command modules (`backup`, `clean`, `config`, `doctor`, `logs`, `models`, `start`, `state`, `status`, `stop`, `workflows`) each registering via `commands.__init__.register`.
  - `airpods/cli/type_defs.py` – shared Typer command mapping type alias.
- Configuration system:
  - `airpods/configuration/` – Pydantic-based config schema, loader, template resolver, and error types.
  - `airpods/configuration/schema.py` – ServiceConfig, RuntimeConfig, CLIConfig, DependenciesConfig models. RuntimeConfig includes `prefer` field ("auto", "podman", "docker") for runtime selection. CLIConfig includes `startup_timeout`/`startup_check_interval` knobs used by `start`.
  - `airpods/configuration/defaults.py` – Built-in default configuration dictionary.
  - `airpods/configuration/loader.py` – Config file discovery, TOML loading, merging, caching.
  - `airpods/configuration/resolver.py` – Template variable resolution (`{{runtime.host_gateway}}`, `{{services.ollama.ports.0.host}}`).
  - Config priority: `$AIRPODS_CONFIG` → `$AIRPODS_HOME/configs/config.toml` → `$AIRPODS_HOME/config.toml` (legacy) → `<repo_root>/configs/config.toml` → `<repo_root>/config.toml` (legacy) → `$XDG_CONFIG_HOME/airpods/configs/config.toml` → `$XDG_CONFIG_HOME/airpods/config.toml` (legacy) → `~/.config/airpods/configs/config.toml` → `~/.config/airpods/config.toml` (legacy) → defaults.
  - Whichever directory provides the active config is treated as `$AIRPODS_HOME`; `configs/`, `volumes/`, and secrets are all created there so runtime assets stay grouped together regardless of which item in the priority list wins.
- Runtime abstraction:
  - `airpods/runtime.py` – Defines `ContainerRuntime` protocol and implements `PodmanRuntime` and `DockerRuntime` adapters. The `get_runtime(prefer)` factory intelligently selects the runtime based on config (`prefer="auto"` auto-detects, preferring Podman; `prefer="podman"` or `prefer="docker"` explicitly selects).
  - `airpods/podman.py` – Podman subprocess wrapper with full API (volumes, images, pods, containers, exec, logs).
  - `airpods/docker.py` – Docker subprocess wrapper mirroring Podman API. Docker's pod abstraction is a logical grouping with host networking.
  - All CLI commands route through `ServiceManager.runtime` for container operations, ensuring runtime-agnostic behavior.
- Supporting modules: `airpods/system.py` (env checks), `airpods/gpu.py` (runtime-aware GPU detection with separate flags for Docker/Podman), `airpods/config.py` (service specs from config), `airpods/logging.py` (Rich console themes), `airpods/ui.py` (Rich tables/panels), `airpods/paths.py` (repo root detection), `airpods/state.py` (state directory management), `podcli` (uv/python wrapper script).
- Supporting modules: `airpods/system.py` (env checks), `airpods/gpu.py` (runtime-aware GPU detection), `airpods/cuda.py` (CUDA selection helpers), `airpods/comfyui.py` (provider/image selection), `airpods/gguf.py` (GGUF download helpers), `airpods/config.py` (service specs from config), `airpods/logging.py` (Rich console themes), `airpods/ui.py` (Rich tables/panels), `airpods/paths.py` (repo root detection), `airpods/state.py` (state directory management). CLI entrypoint is `airpods.cli:main` via `[project.scripts]` in `pyproject.toml`.
- Pod specs dynamically generated from configuration. Service metadata includes `needs_webui_secret` flag for automatic secret injection. Easy to extend services via config files.
- All pods use host networking (`--network host`) for simplicity and maximum compatibility. Services communicate via `localhost:port`. For Docker, "pods" are logical groupings tracked by naming convention; for Podman, they are actual pod resources.
- Errors surfaced with clear remediation (install runtime, start podman machine, check GPU drivers, etc.).

## Data & Images
- Volumes: bind mounts under `$AIRPODS_HOME/volumes/` (resolved from `bind://...`) including `airpods_ollama_data`, `airpods_webui_data`, `webui_plugins`, `airpods_comfyui_data`, `comfyui_custom_nodes`, `comfyui/workspace`, and the shared GGUF store `airpods_models/gguf`.
- Images: `docker.io/ollama/ollama:latest`, `ghcr.io/open-webui/open-webui:latest`, ComfyUI image selected by `runtime.cuda_version` + `runtime.comfyui_provider`, and `ghcr.io/ggml-org/llama.cpp:server` (or `:server-cuda` when GPU-enabled); pulled during `start` (or via `start --pre-fetch`).
- Secrets: Open WebUI secret persisted at `$AIRPODS_HOME/configs/webui_secret` (or `$XDG_CONFIG_HOME/airpods/configs/webui_secret` or `~/.config/airpods/configs/webui_secret`) during `start` when Open WebUI is enabled, injected via the `needs_webui_secret` flag.
- Networking: All services use host networking. Open WebUI targets Ollama via `http://localhost:11434` (configurable via templates).
- Configuration: Optional `config.toml` in `configs/` subdirectory at `$AIRPODS_HOME` or XDG paths; deep-merged with defaults. All airpods configuration files (config.toml, webui_secret, etc.) are stored together in the `configs/` subdirectory.
- Plugins: Open WebUI plugins live in `plugins/open-webui/` and are synced to `webui_plugins` volume during `start`. ComfyUI custom nodes live in `plugins/comfyui/custom_nodes/` and are synced to `comfyui_custom_nodes` volume during `start`. Both support directory-based packages and single-file modules.

## Testing Approach
- Unit tests mock subprocess interactions to validate command flow and flags.
- Configuration tests verify schema validation, template resolution, and file merging.
- Test fixtures isolate config artifacts per test via `AIRPODS_HOME` override.
- Integration (later): optional Podman-in-Podman smoke tests; GPU checks skipped when unavailable.

## Development Workflow
- Version bump rules (update `pyproject.toml` before committing):
  - Patch bump (e.g., `0.9.1` → `0.9.2`) for bug fixes and small UX/behavior improvements.
  - Minor bump (e.g., `0.9.1` → `0.10.0`) for large features or meaningful command-surface additions.
  - Major bump only for breaking changes.
- The CI workflow under `.github/workflows/test.yml` now has a `test` job that pins `ubuntu-24.04`, iterates over Python `3.10`‑`3.13`, installs/uses each interpreter via `uv python`, syncs dev/extras, runs `uv run pytest --cov=airpods --cov-report=term-missing --cov-report=xml`, and publishes Codecov only from the 3.13 row.
- The paired `lint` job also targets `ubuntu-24.04`, installs UV, and validates that `python3 -m compileall airpods` can compile every module in the tree.
- Run `uv run pytest` locally when making changes and keep formatting consistency with `uv format`.
- Install `pre-commit` (part of the `dev` extras) and call `pre-commit run --all-files` before finishing your work; the hook runs `uv format`, Prettier checks on YAML/TOML/Markdown, the full pytest suite with coverage, and `python3 -m compileall airpods`, mirroring the CI jobs.
- Before committing, bump the version in `pyproject.toml`: use minor version bumps for large features and patch bumps for everything else (bug fixes, small improvements, etc.).
- Commit messages use lowercase prefixes such as `docs:`, `refactor:`, `feat:`, `fix:`, or `chore:` followed by a concise summary.
