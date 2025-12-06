# docs/cuda-detection

## CUDA Auto-Detection

Airpods automatically detects your GPU's compute capability and selects the appropriate CUDA version for ComfyUI to ensure optimal GPU utilization.

## How It Works

1. **GPU Detection**: Uses `nvidia-smi` to query GPU name and compute capability
2. **Version Mapping**: Maps compute capability to compatible CUDA versions
3. **Image Selection**: Chooses the appropriate ComfyUI Docker image variant
4. **Fallback**: Uses cu126 (CUDA 12.6) as a backwards-compatible default

## Compute Capability → CUDA Version Mapping

| GPU Architecture | Compute Capability | Max CUDA Version | Selected Image |
|-----------------|-------------------|------------------|----------------|
| Kepler/Maxwell | 3.5 - 5.3 | CUDA 11.8 | cu118-slim |
| Pascal/Turing | 6.0 - 7.5 | CUDA 12.6 | cu126-megapak |
| Ampere | 8.0 - 8.9 | CUDA 12.8 | cu128-slim |
| Hopper+ | 9.0+ | CUDA 13.0+ | cu130-slim |

## Configuration

### Auto-Detection (Default)

```toml
# config.toml
[runtime]
cuda_version = "auto"  # Detect automatically
```

### Global Override

Force a specific CUDA version for all services:

```toml
[runtime]
cuda_version = "cu126"  # Use CUDA 12.6 for all services
```

### Per-Service Override

Override CUDA version for specific services:

```toml
[services.comfyui]
cuda_override = "cu128"  # Force CUDA 12.8 for ComfyUI only
```

### Force CPU Mode

Disable GPU entirely:

```toml
[runtime]
cuda_version = "cpu"
```

## Priority Chain

The CUDA version is resolved in this order:

1. **Service override** (`services.comfyui.cuda_override`)
2. **Runtime setting** (`runtime.cuda_version`)
3. **Auto-detection** (via compute capability)
4. **Safe fallback** (cu126 - backwards compatible)

## Checking Your GPU

### Find Your GPU's Compute Capability

```bash
nvidia-smi --query-gpu=name,compute_cap --format=csv,noheader
```

Example output:
```
NVIDIA GeForce GTX 1650, 7.5
```

### Check What Airpods Detects

Run the doctor command to see detected GPU info:

```bash
airpods doctor
```

Example output:
```
GPU: ✓ enabled (NVIDIA GeForce GTX 1650)
CUDA: ✓ CUDA 12.6 (cu126) for compute 7.5
```

## Troubleshooting

### GPU Not Being Utilized

1. **Check detection**: Run `airpods doctor` to see what CUDA version was selected
2. **Verify logs**: Check ComfyUI logs for GPU initialization messages
3. **Manual override**: Try forcing a specific CUDA version

Example fix for older GPUs:
```toml
[services.comfyui]
cuda_override = "cu126"  # Force CUDA 12.6 for older GPUs
```

### Wrong CUDA Version Selected

Use configuration overrides to force the correct version:

```toml
# For GTX 1060 (compute 6.1) that needs CUDA 12.6
[services.comfyui]
cuda_override = "cu126"
```

### ComfyUI Falls Back to CPU

This happens when:
- GPU not detected by nvidia-smi
- CUDA version incompatible with your GPU
- GPU drivers not installed

**Solutions:**
1. Install NVIDIA drivers
2. Verify `nvidia-smi` works
3. Force a compatible CUDA version

### Detection Failures

If auto-detection fails, airpods falls back to cu126 (CUDA 12.6) which works with most modern GPUs back to Pascal architecture (GTX 10-series).

To troubleshoot detection issues:
```bash
# Test nvidia-smi directly
nvidia-smi --query-gpu=name,compute_cap --format=csv,noheader

# Check airpods detection
airpods doctor
```

## Why cu126 Default?

cu126 (CUDA 12.6) is chosen as the default because:

- **Backwards compatible**: Works with GPUs back to compute 6.0 (Pascal/GTX 10-series)
- **Stable**: Well-tested and widely supported
- **Optimal balance**: Good performance without requiring latest GPU architectures
- **Your use case**: Specifically works with older GPUs that need CUDA 12.6 instead of 12.8

## Available Image Variants

| CUDA Version | Docker Image | GPU Support |
|-------------|--------------|-------------|
| cu118-slim | yanwk/comfyui-boot:cu118-slim | Kepler, Maxwell |
| cu126-megapak | yanwk/comfyui-boot:cu126-megapak | Pascal, Turing |
| cu128-slim | yanwk/comfyui-boot:cu128-slim | Ampere |
| cu130-slim | yanwk/comfyui-boot:cu130-slim | Hopper+ |
| cpu | yanwk/comfyui-boot:cpu | No GPU |

## Examples

### Automatic (Recommended)

```toml
# Let airpods detect and choose
[runtime]
cuda_version = "auto"
```

For a GTX 1650 (compute 7.5), this automatically selects cu126.

### Manual Override for Performance

```toml
# Force latest CUDA for RTX 4090
[services.comfyui]
cuda_override = "cu130"
```

### Compatibility Override

```toml
# Force older CUDA for GTX 1060
[services.comfyui]
cuda_override = "cu126"
```

### CPU Fallback

```toml
# Disable GPU entirely
[runtime]
cuda_version = "cpu"
```

## CLI Output Examples

### Successful Detection
```bash
$ airpods start
GPU: ✓ enabled (NVIDIA GeForce RTX 3080)
CUDA: ✓ CUDA 12.8 (cu128) for compute 8.6
ComfyUI CUDA: auto-detected (compute 8.6 → cu128) → docker.io/yanwk/comfyui-boot:cu128-slim
```

### Override in Use
```bash
$ airpods start
GPU: ✓ enabled (NVIDIA GeForce GTX 1650)
CUDA: ✓ CUDA 12.6 (cu126) for compute 7.5
ComfyUI CUDA: service override (cu126) → docker.io/yanwk/comfyui-boot:cu126-megapak
```

### Detection Failure
```bash
$ airpods start
GPU: ⚠ not detected (nvidia-smi not found)
CUDA: ⚠ not available (nvidia-smi not found)
ComfyUI CUDA: fallback (GPU detection failed: nvidia-smi not found) → docker.io/yanwk/comfyui-boot:cu126-megapak
