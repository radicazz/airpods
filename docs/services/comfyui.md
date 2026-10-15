# docs/services/comfyui

ComfyUI is enabled by default and listens on `http://localhost:8188`.

```bash
airpods start comfyui --wait
airpods workflows path
airpods status comfyui
```

Aliases are `comfy` and `comfy-ui`. Airpods selects a CUDA image and provider from the configuration and GPU checks; see [CUDA selection](../configuration/cuda-detection.md). `airpods start comfyui --cpu` forces the CPU image.

## Data and Custom Nodes

Provider-specific bind mounts live under `<state-root>/volumes/`:

| Provider   | Main storage                                                 | Models                                          |
| ---------- | ------------------------------------------------------------ | ----------------------------------------------- |
| `yanwk`    | `comfyui/workspace` → `/workspace`                           | `airpods_comfyui_data` → `/root/ComfyUI/models` |
| `mmartial` | `comfyui/basedir` → `/basedir`, `comfyui/run` → `/comfy/mnt` | `comfyui/basedir/models` → `/basedir/models`    |

Both mount `comfyui_custom_nodes` at `/root/ComfyUI/custom_nodes`. Use `workflows path` to see paths resolved for the active provider.

Bundled [custom nodes](../../plugins/comfyui/README.md) sync during `start`. Additional git/local nodes come from [configuration](../commands/config.md#comfyui-custom-nodes); requirements install inside the container. Starting an already-running service can sync files, but ComfyUI needs a restart to load changed nodes:

```bash
airpods stop comfyui
airpods start comfyui --wait
```

The bundled [AirPods Tools](../../plugins/comfyui/custom_nodes/comfyui-airpods/README.md) supply llama.cpp/Ollama text and chat nodes plus text utilities. Start the corresponding backend and select its node in ComfyUI. Embedding nodes are not implemented.

## Workflows

See [workflow commands](../commands/workflows.md) for import, model sync, and cleanup. No example workflow files are currently bundled; import your own JSON and optional companion mapping.
