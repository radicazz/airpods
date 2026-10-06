# ComfyUI Plugins

This directory contains ComfyUI custom nodes and workflows that are part of the airpods project.

## Structure

```
plugins/comfyui/
├── custom_nodes/         # Custom nodes synced to ComfyUI
│   └── comfyui-airpods/  # Airpods integration nodes
└── workflows/           # Optional repo workflows with model mappings
```

## Custom Nodes

Custom nodes in `custom_nodes/` are automatically synced to ComfyUI's `custom_nodes` directory when you run `airpods start comfyui`.
Additional nodes can be installed via `services.comfyui.custom_nodes.install` in `config.toml`.

Custom nodes can be in two formats:

### 1. Directory-based packages (recommended)

Directories with an `__init__.py` file:

```
plugins/comfyui/custom_nodes/
├── my_custom_node/
│   ├── __init__.py       # Required - marks this as a Python package
│   ├── node.py           # Your node implementation
│   └── requirements.txt  # Optional - node dependencies
```

### 2. Single-file custom nodes

Simple `.py` files placed directly in `custom_nodes/`:

```
plugins/comfyui/custom_nodes/
├── simple_node.py
```

### Syncing

Custom nodes are automatically synced when you run:

```bash
airpods start comfyui
```

The sync process:

- Copies all directory-based packages (must have `__init__.py`)
- Copies all single `.py` files
- Removes old custom nodes that no longer exist in source (when `prune=True`)
- Only updates files that have changed (based on modification time)

## Workflows

The `workflows/` directory contains example workflows with companion TOML files that map model filenames to download URLs.

### Importing Workflows

Use the `airpods workflows add` command to import workflows into your ComfyUI workspace:

```bash
# List available workflows
airpods workflows add

# Import a workflow from the repo
airpods workflows add my-workflow

# Import and automatically download required models
airpods workflows add my-workflow --sync

# List saved workflows (same as "airpods workflows list")
airpods workflows sync

# Sync missing models for a workflow
airpods workflows sync my-workflow
```

### Workflow Format

Each workflow consists of:

- **JSON file**: ComfyUI workflow in prompt or UI format
- **TOML file** (optional): Model mapping with filenames, folders, and download URLs

Example TOML mapping:

```toml
[models."model-name.safetensors"]
url = "https://huggingface.co/org/repo/resolve/main/model.safetensors"
folder = "checkpoints"
```

If a mapping TOML exists alongside a workflow (same name), `airpods workflows sync`
will automatically use it without needing `--map`.

## Notes

- Custom nodes are copied to `$AIRPODS_HOME/volumes/comfyui_custom_nodes/`
- This directory is mounted into ComfyUI at `/root/ComfyUI/custom_nodes`
- ComfyUI auto-discovers custom nodes on startup
- Directories without `__init__.py` are ignored
- Files/directories starting with `.` or `_` are ignored
