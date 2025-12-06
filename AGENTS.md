# Agents & Plan

## Intent
Provide a Rich + Typer-powered CLI (packaged under `airpods/cli/`, installed as the `airpods` command via uv tools) that orchestrates local AI services via Podman. Services are configurable via TOML files with template support. Services: Ollama (GGUF-capable), Open WebUI wired to Ollama, and ComfyUI (using yanwk/comfyui-boot community image; future plan to fork and build custom).

## Command Surface
- Global options: `-v/--version` prints the CLI version; `-h/--help` shows the custom help view plus alias table.
- `start [service...]`: Ensures volumes/images, then launches pods (default both) while explaining when networks, volumes, pods, or containers are reused vs newly created. Waits for each service to report healthy (HTTP ping when available) for up to `cli.startup_timeout` seconds, polling every `cli.startup_check_interval` seconds, with health-less services marked ready once their pod is running. Skips recreation if containers are already running. GPU auto-detected and attached to Ollama; CPU fallback allowed. `--init/-i` performs the dependency checks + resource creation/image pull flow without starting containers, replacing the standalone `init` command. Exposed aliases: `up`.
- `stop [service...]`: Graceful stop; optional removal of pods while preserving volumes by default, with an interactive confirmation prompt before destructive removal. Exposed aliases: `down`.
- `status [service...]`: Compact Rich table (Service / Status / Info) summarizing HTTP health plus friendly URLs for running pods, or pod status + port summaries for stopped ones; redundant columns (pod name, uptime, counts) were removed for readability. Exposed aliases: `ps`.
- `logs [service...]`: Tail logs for specified services or all; supports follow/since/lines.
- `doctor`: Re-run checks without creating resources; surfaces remediation hints without touching pods/volumes.
- `clean`: Remove volumes, images, configs, and user data created by airpods. Offers granular control via flags:
  - `--all/-a`: Remove everything (pods, volumes, images, network, configs)
  - `--pods/-p`: Stop and remove all pods and containers
  - `--volumes/-v`: Remove Podman volumes and bind mount directories
  - `--images/-i`: Remove pulled container images
  - `--network/-n`: Remove the airpods network
  - `--configs/-c`: Remove config files (config.toml, webui_secret, webui_admin_password)
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
  - `airpods/cli/common.py` – shared constants, service manager, and Podman/dependency helpers.
  - `airpods/cli/help.py` – Rich-powered help/alias rendering tables used by the root callback.
  - `airpods/cli/status_view.py` – status table + health probing utilities.
  - `airpods/cli/commands/` – individual command modules (`doctor`, `start`, `stop`, `status`, `logs`, `version`, `config`, `clean`) each registering via `commands.__init__.register`.
  - `airpods/cli/type_defs.py` – shared Typer command mapping type alias.
- Configuration system:
  - `airpods/configuration/` – Pydantic-based config schema, loader, template resolver, and error types.
  - `airpods/configuration/schema.py` – ServiceConfig, RuntimeConfig, CLIConfig, DependenciesConfig models (CLIConfig includes `startup_timeout`/`startup_check_interval` knobs used by `start`).
  - `airpods/configuration/defaults.py` – Built-in default configuration dictionary.
  - `airpods/configuration/loader.py` – Config file discovery, TOML loading, merging, caching.
  - `airpods/configuration/resolver.py` – Template variable resolution (`{{runtime.host_gateway}}`, `{{services.ollama.ports.0.host}}`).
  - Config priority: `$AIRPODS_CONFIG` → `$AIRPODS_HOME/configs/config.toml` → `$AIRPODS_HOME/config.toml` (legacy) → `<repo_root>/configs/config.toml` → `<repo_root>/config.toml` (legacy) → `$XDG_CONFIG_HOME/airpods/configs/config.toml` → `$XDG_CONFIG_HOME/airpods/config.toml` (legacy) → `~/.config/airpods/configs/config.toml` → `~/.config/airpods/config.toml` (legacy) → defaults.
  - Whichever directory provides the active config is treated as `$AIRPODS_HOME`; `configs/`, `volumes/`, and secrets are all created there so runtime assets stay grouped together regardless of which item in the priority list wins.
- Supporting modules: `airpods/podman.py` (subprocess wrapper), `airpods/system.py` (env checks, GPU detection), `airpods/config.py` (service specs from config), `airpods/logging.py` (Rich console themes), `airpods/ui.py` (Rich tables/panels), `airpods/paths.py` (repo root detection), `airpods/state.py` (state directory management), `podcli` (uv/python wrapper script).
- Pod specs dynamically generated from configuration. Service metadata includes `needs_webui_secret` flag for automatic secret injection. Easy to extend services via config files.
- Network aliases are configured at the pod level (not container level) since containers in pods share the pod's network namespace.
- Errors surfaced with clear remediation (install Podman, start podman machine, check GPU drivers).

## Data & Images
- Volumes: `airpods_ollama_data`, `airpods_webui_data`, and `airpods_comfyui_data` are bind-mounted under `$AIRPODS_HOME/volumes/` (e.g., `$AIRPODS_HOME/volumes/airpods_ollama_data`), while the ComfyUI workspace bind (`bind://comfyui/workspace`) lives at `$AIRPODS_HOME/volumes/comfyui/workspace`.
- Images: `docker.io/ollama/ollama:latest`, `ghcr.io/open-webui/open-webui:latest`, `docker.io/yanwk/comfyui-boot:cu128-slim`; pulled during `start --init`/`start`.
- Secrets: Open WebUI secret persisted at `$AIRPODS_HOME/configs/webui_secret` and admin password at `$AIRPODS_HOME/configs/webui_admin_password` (or corresponding XDG paths) during `start --init`, injected on start via `needs_webui_secret` flag. The admin user (`airpods@localhost`) is automatically created in Open WebUI's database for plugin ownership.
- Networking: Open WebUI targets Ollama via the Podman alias `http://ollama:11434` (configurable via templates).
- Configuration: Optional `config.toml` in `configs/` subdirectory at `$AIRPODS_HOME` or XDG paths; deep-merged with defaults. All airpods configuration files (config.toml, webui_secret, webui_admin_password, etc.) are stored together in the `configs/` subdirectory.

## Testing Approach
- Unit tests mock subprocess interactions to validate command flow and flags.
- Configuration tests verify schema validation, template resolution, and file merging.
- Test fixtures isolate config artifacts per test via `AIRPODS_HOME` override.
- Integration (later): optional Podman-in-Podman smoke tests; GPU checks skipped when unavailable.

## Development Workflow
- The CI workflow under `.github/workflows/test.yml` now has a `test` job that pins `ubuntu-24.04`, iterates over Python `3.10`‑`3.13`, installs/uses each interpreter via `uv python`, syncs dev/extras, runs `uv run pytest --cov=airpods --cov-report=term-missing --cov-report=xml`, and publishes Codecov only from the 3.13 row.
- The paired `lint` job also targets `ubuntu-24.04`, installs UV, and validates that `python3 -m compileall airpods` can compile every module in the tree.
- Run `uv run pytest` locally when making changes and keep formatting consistency with `uv format`.
- Install `pre-commit` (part of the `dev` extras) and call `pre-commit run --all-files` before finishing your work; the hook runs `uv format`, Prettier checks on YAML/TOML/Markdown, the full pytest suite with coverage, and `python3 -m compileall airpods`, mirroring the CI jobs.
- Commit messages use lowercase prefixes such as `docs:`, `refactor:`, `feat:`, `fix:`, or `chore:` followed by a concise summary.
