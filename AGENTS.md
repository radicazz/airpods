# Agents & Plan

## Intent
Provide a Rich + Typer-powered CLI (packaged under `airpods/cli/`, installed as the `airpods` command via uv tools) that orchestrates local AI services via Podman. Services are configurable via TOML files with template support. Initial services: Ollama (GGUF-capable) and Open WebUI wired to Ollama. Future additions: ComfyUI and others.

## Command Surface
- Global options: `-v/--version` prints the CLI version; `-h/--help` shows the custom help view plus alias table.
- `init`: Verify dependencies (podman, podman-compose, uv, optional nvidia-smi), create volumes, pull images, summarize readiness, and report whether each resource was created or already present.
- `start [service...]`: Ensure volumes/images, then launch pods (default both) while explaining when networks, volumes, pods, or containers are reused vs newly created. Prompts before replacing existing containers unless the user passes `--force`. GPU auto-detected and attached to Ollama; CPU fallback allowed. Exposed aliases: `up`.
- `stop [service...]`: Graceful stop; optional removal of pods while preserving volumes by default, with an interactive confirmation prompt before destructive removal. Exposed aliases: `down`.
- `status [service...]`: Rich table showing pod/container state, ports, uptime, and an HTTP ping per service. Exposed aliases: `ps`.
- `logs [service...]`: Tail logs for specified services or all; supports follow/since/lines.
- `doctor`: Re-run checks without creating resources; surfaces remediation hints without touching pods/volumes.
- `config`: Manage configuration with subcommands:
  - `init`: Create default config file at `$AIRPODS_HOME/config.toml`
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
  - `airpods/cli/commands/` – individual command modules (`init`, `doctor`, `start`, `stop`, `status`, `logs`, `version`, `config`) each registering via `commands.__init__.register`.
  - `airpods/cli/type_defs.py` – shared Typer command mapping type alias.
- Configuration system:
  - `airpods/configuration/` – Pydantic-based config schema, loader, template resolver, and error types.
  - `airpods/configuration/schema.py` – ServiceConfig, RuntimeConfig, CLIConfig, DependenciesConfig models.
  - `airpods/configuration/defaults.py` – Built-in default configuration dictionary.
  - `airpods/configuration/loader.py` – Config file discovery, TOML loading, merging, caching.
  - `airpods/configuration/resolver.py` – Template variable resolution (`{{runtime.host_gateway}}`, `{{services.ollama.ports.0.host}}`).
  - Config priority: `$AIRPODS_CONFIG` → `$AIRPODS_HOME/config.toml` → `<repo_root>/config.toml` → `$XDG_CONFIG_HOME/airpods/config.toml` → `~/.config/airpods/config.toml` → defaults.
- Supporting modules: `airpods/podman.py` (subprocess wrapper), `airpods/system.py` (env checks, GPU detection), `airpods/config.py` (service specs from config), `airpods/logging.py` (Rich console themes), `airpods/ui.py` (Rich tables/panels), `airpods/paths.py` (repo root detection), `airpods/state.py` (state directory management), `podcli` (uv/python wrapper script).
- Pod specs dynamically generated from configuration. Service metadata includes `needs_webui_secret` flag for automatic secret injection. Easy to extend services via config files.
- Errors surfaced with clear remediation (install Podman, start podman machine, check GPU drivers).

## Data & Images
- Volumes: `airpods_ollama_data` for models, `airpods_webui_data` for Open WebUI data, `airpods_comfyui_models` for ComfyUI (when enabled).
- Images: `docker.io/ollama/ollama:latest`, `ghcr.io/open-webui/open-webui:latest`, `ghcr.io/comfyanonymous/comfyui:latest`; pulled during `init`/`start`.
- Secrets: Open WebUI secret persisted at `~/.config/airpods/webui_secret` (or `$XDG_CONFIG_HOME/airpods/webui_secret`) during `init`, injected on start via `needs_webui_secret` flag.
- Networking: Open WebUI targets Ollama via host-published `http://host.containers.internal:11434` (configurable via templates).
- Configuration: Optional `config.toml` at `$AIRPODS_HOME` or XDG paths; deep-merged with defaults.

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
