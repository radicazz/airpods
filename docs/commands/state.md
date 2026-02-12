# docs/commands/state

The `airpods state` command group manages local state. Use it to back up, restore, or clean stateful data without copying massive model files.

## `airpods state backup`

Create a compressed archive containing:
- `configs/` (config.toml, webui_secret, other config files)
- Open WebUI database (`webui.db`) plus optional SQLite `.dump`
- Open WebUI plugins stored under `webui_plugins`
- Ollama model metadata (names, digests, URLs, params, but **not** GGUF blobs)
- Manifest with version info for airpods, Open WebUI, and Ollama

```bash
# Default backup path: ./airpods-backup-<timestamp>.tar.gz
airpods state backup

# Save to custom directory/name without SQL dump
airpods state backup --dest ~/backups --filename my-airpods.tgz --no-sql-dump
```

**Options:**
- `--dest PATH`: Directory to store the archive (default: `cwd`)
- `--filename NAME`: Override archive filename
- `--sql-dump/--no-sql-dump`: Include SQLite `.dump` via running container (default: on)

> [!NOTE]
> Model binaries (GGUF, diffusion checkpoints, etc.) aren’t copied. Only metadata is captured so you can re-pull the exact models later.

## `airpods state restore`

Unpack a backup archive and restore configs, WebUI data, and metadata into fresh volumes.

```bash
# Restore everything, backing up existing configs/db first
airpods state restore ~/backups/airpods-backup-20250712.tar.gz

# Restore configs only, skipping database and metadata
airpods state restore archive.tgz --skip-db --skip-models
```

**Arguments & Options:**
- `<archive>`: Path to `.tar.gz` produced by `airpods state backup`
- `--backup-existing/--no-backup-existing`: Copy current configs/DB before overwrite (default: on)
- `--skip-configs`: Don’t restore config files
- `--skip-db`: Don’t restore Open WebUI database (raw copy or SQL dump)
- `--skip-plugins`: Don’t restore plugin files
- `--skip-models`: Don’t restore Ollama metadata JSON

### Restore Workflow
1. Validate archive and extract into a temp directory
2. Copy configs into `$AIRPODS_HOME/configs` (optionally backing up current files)
3. Restore WebUI database (`webui.db`) or rebuild from `.dump`
4. Rehydrate `webui_plugins`
5. Save Ollama metadata + manifest under `$AIRPODS_HOME/configs/restores/`
6. Print reminders to re-pull Ollama models and restart services

### Best Practices
- Run `airpods stop` before backing up to ensure clean SQLite copies
- Store archives outside of `$AIRPODS_HOME` so they survive `airpods state clean --all`
- After restoring, re-pull Ollama models using the metadata file saved in `configs/restores/`
- Keep sensitive archives encrypted if they contain user data

With these commands you can safely nuke volumes (`airpods state clean --volumes`) and bring them back later without losing Open WebUI users, chats, or plugin state.

## `airpods state clean`

Remove volumes, images, configs, and user data created by airpods.

```bash
# Remove everything created by airpods
airpods state clean --all

# Remove only volumes
airpods state clean --volumes

# Remove only images without prompts
airpods state clean --images --force

# Preview what would be removed
airpods state clean --all --dry-run
```

**Options:**
- `--all, -a`: Remove all targets (pods, volumes, images, configs)
- `--pods, -p`: Stop and remove service pods/containers
- `--volumes, -v`: Remove configured container volumes and bind-mounted data directories
- `--images, -i`: Remove pulled container images
- `--configs, -c`: Remove config files under `$AIRPODS_HOME/configs`
- `--force, -f`: Skip interactive confirmation prompts
- `--dry-run`: Show the cleanup plan without deleting anything
- `--backup-config / --no-backup-config`: Backup `config.toml` before deleting configs (default: backup enabled)

**Notes:**
- Running `state clean` without target flags exits with a usage error.
- `--dry-run` is the safest way to confirm exactly what will be touched.
- `--all` expands to `--pods --volumes --images --configs`.
