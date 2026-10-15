# Agents & Plan

## Intent

Maintain a Rich + Typer CLI that orchestrates local AI services through Podman or Docker. Supported services are Ollama, Open WebUI, ComfyUI, and llama.cpp. Keep service behavior configurable through TOML and templates; see [project goals](docs/goals.md).

## Command Surface

- Global options: `-v/--version`, `-V/--verbose`, and `-h/--help`. Help includes command aliases.
- `start [service...]` (`up`, `run`): start enabled services by default, reuse running containers, and explain resource creation/reuse. Preflight checks, plugin sync, volume preparation, and llama.cpp model validation precede the final start confirmation. `--yes` or `cli.auto_confirm` skips start/download confirmations. `--pre-fetch` selects effective CPU/GPU images and downloads missing images without creating pods, volumes, or secrets; it can bootstrap configuration. `--sequential` overrides concurrent pulls. `--wait` checks readiness, including already-running services, using `cli.startup_timeout` and `cli.startup_check_interval`; timeout/failure exits with status 1. Services without HTTP health are ready when running.
- `stop [service...]` (`down`): stop services; `--remove` confirms before removing pods/containers and preserves volumes.
- `status [service...]` (`ps`, `info`): compact Service / Status / Info table with HTTP health and URLs or stopped pod/port information.
- `logs [service...]`: logs with follow, since, and line-count options.
- `doctor` (`health`): inspect dependencies, runtime/GPU setup, llama.cpp resources, and legacy ComfyUI imports without changing pods or volumes.
- `models` (`model`): Ollama `list` (`ls`), `pull`, `info`, `remove` (`rm`), HuggingFace GGUF `search`, and local `gguf list/pull/remove`. Search and local GGUF operations do not need a running Ollama service. See [model commands](docs/commands/models.md).
- `workflows`: `add`, `list` (`ls`), `sync`, `desync`, `pull`, `remove` (`delete`), `path`, and `api`. See [workflow commands](docs/commands/workflows.md).
- `state`: `backup`, `restore`, and `clean`. Backups include configs, a consistent WebUI SQLite snapshot, WebUI plugins, Ollama metadata, and non-GGUF files in the GGUF store; model binaries are excluded. Restore requires WebUI to be stopped when restoring its database. `clean` requires target flags, supports `--dry-run`, and confirms unless `--force` or configured auto-confirm is used. See [state commands](docs/commands/state.md).
- `config`: `init`, `show`, `path`, `edit`, `validate`, `reset`, `get`, and `set`. Help/version and configuration repair work without a runtime or valid active config. See [configuration](docs/commands/config.md).
- Service aliases: `comfy`/`comfy-ui` → `comfyui`; `llama`/`llama-cpp`/`llama.cpp` → `llamacpp`.

## Architecture

- `airpods/cli/__init__.py`: Typer app, command registration, and compatibility exports. `cli/commands/` contains command implementations; `common.py` lazily initializes config and the service manager; `help.py`, `status_view.py`, and `completions.py` handle presentation/completion. `cli/pull.py` handles concurrent image downloads; `launch.py` handles startup and plugin preparation.
- `airpods/configuration/`: Pydantic schema, defaults, TOML discovery/deep merge/cache, and template resolution. `airpods/config.py` builds service specs and selects effective images; `services.py` manages service operations.
- `airpods/runtime.py`: `ContainerRuntime` protocol, adapters, and runtime selection (`auto` prefers Podman). `podman.py` manages real pods; `docker.py` groups configured containers into logical pods. Commands operate through `ServiceManager.runtime`.
- `airpods/_container_cli.py`: shared subprocess/volume/image/container helpers. Keep stderr separate from captured stdout so warnings cannot corrupt JSON or formatted output; include both streams in failure diagnostics. Distinguish missing containers from runtime failures.
- `gpu.py`, `system.py`, `cuda.py`, and `comfyui.py`: dependency/GPU checks, runtime-specific GPU flags, CUDA/provider selection, and provider-specific mounts. `gguf.py`, `ollama.py`, and `files.py`: model operations and managed file/download helpers.
- `state.py` and `paths.py`: state directories, secrets, and repo detection. The active config determines the state root; explicit `AIRPODS_HOME` isolates discovery when no `AIRPODS_CONFIG` is set. See the exact precedence and layout in [configuration](docs/commands/config.md).
- `plugins.py` and `custom_nodes.py`: bundled plugin sync, best-effort WebUI database imports, and configured ComfyUI git/local node installation. See the plugin READMEs and nested AGENTS instructions before modifying them.
- Installed entrypoint: `airpods.cli:main` from `pyproject.toml`. `podcli` wraps local uv/Python execution.

## Runtime and Data Invariants

- Both runtimes use host networking. Services communicate via `localhost:<host-port>`; bridge networks, network aliases, and port forwarding are not implemented. Configure each process to listen on its intended host port.
- Bind sources (`bind://...`) resolve under `<state-root>/volumes/`. Defaults include `airpods_ollama_data`, `airpods_webui_data`, `webui_plugins`, `comfyui_custom_nodes`, and `airpods_models/gguf`. ComfyUI mounts vary by provider; use `airpods workflows path` to inspect them.
- Open WebUI's persistent session secret is `<state-root>/configs/webui_secret`, injected via `needs_webui_secret`. Ollama connection auto-configuration is opt-in (`services.open-webui.auto_configure_ollama`).
- Effective CPU/GPU image selection must agree between pre-fetch and startup. Reuse existing resources and preserve user data unless removal was explicitly requested.
- Surface errors with actionable runtime, driver, configuration, or model remediation.

## Testing and Development

- Tests mock subprocess/container interactions and isolate state via `AIRPODS_HOME`. Add meaningful regression coverage for runtime failures; live container/GPU checks are separate from mocked tests.
- Run `uv sync --all-extras`, `uv run pytest`, and `uv run pre-commit run --all-files` before finishing. The full suite enforces 55% coverage; targeted debugging can use `--no-cov` but does not replace the full check.
- Format with `uv format` or `uv format -- <paths>`. Pre-commit also checks Markdown/YAML/TOML with Prettier, file hygiene, the full pytest suite with coverage, and `python3 -m compileall airpods`.
- `.github/workflows/test.yml` runs tests on Ubuntu 24.04 with Python 3.10–3.13 selected through `UV_PYTHON`. Only Python 3.13 publishes coverage. Its `quality` job runs all pre-commit checks on Python 3.13.
- Before committing, update `pyproject.toml` and `uv.lock`: patch bump for fixes/small improvements; minor for large features or meaningful command additions; major for breaking changes.
- Inspect staged diffs and use logical commits with lowercase Conventional Commit prefixes (`fix:`, `feat:`, `docs:`, `refactor:`, `chore:`).
