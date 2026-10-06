# docs/configuration/cuda-detection

Airpods automatically detects your GPU and selects the right CUDA version for ComfyUI.

## How It Works

- Detects your GPU's compute capability via `nvidia-smi`
- Maps compute capability to the best CUDA version
- Selects the appropriate ComfyUI Docker image
- Falls back to CUDA 12.6 if detection fails (works with most GPUs)

## Configuration

### Auto-Detection (Default)

```toml
[runtime]
cuda_version = "auto"  # Let airpods choose
```

### Manual Override

```toml
[runtime]
cuda_version = "cu126"  # Force CUDA 12.6

# Or per-service:
[services.comfyui]
cuda_override = "cu128"  # Force CUDA 12.8 for ComfyUI only
```

### CPU Only

```toml
[runtime]
cuda_version = "cpu"  # Disable GPU
```

## Check Your Setup

```bash
airpods doctor  # Shows detected GPU and CUDA version
```

## Common Issues

**GPU not being used?** Try forcing CUDA 12.6:

```toml
[services.comfyui]
cuda_override = "cu126"
```

**Detection failed?** Install NVIDIA drivers and verify `nvidia-smi` works.

## GPU → CUDA Mapping

| GPU Series           | CUDA Version | Image         |
| -------------------- | ------------ | ------------- |
| GTX 10/RTX 20 series | cu126        | cu126-megapak |
| RTX 30/40 series     | cu128        | cu128-slim    |
| Older GPUs           | cu118        | cu118-slim    |
| No GPU               | cpu          | cpu           |

The default fallback (cu126) works with most modern GPUs.
