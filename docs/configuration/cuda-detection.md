# docs/configuration/cuda-detection

Airpods uses GPU detection, CUDA selection, and runtime passthrough checks to choose effective service images. Inspect the detected setup with `airpods doctor`.

## Configuration

```toml
[runtime]
cuda_version = "auto"  # auto, cu118, cu126, cu128, cu130, cpu
comfyui_provider = "auto"  # auto, yanwk, mmartial

[services.comfyui]
cuda_override = "cu128"  # optional per-service image selection override
```

ComfyUI selection priority is `cuda_override`, then a non-auto runtime setting, then detected compute capability, then `cu126` when capability detection fails. The fallback is an image-selection default, not a driver compatibility guarantee.

## Selection Implemented by Airpods

| Detected compute capability | CUDA selection | Automatic provider |
| --------------------------- | -------------- | ------------------ |
| 3.5–5.3 entries             | `cu118`        | `mmartial`         |
| 6.x                         | `cu126`        | `mmartial`         |
| 7.x                         | `cu126`        | `yanwk`            |
| 8.x                         | `cu128`        | `yanwk`            |
| 9.0 and newer fallback      | `cu130`        | `yanwk`            |

This describes the code's mapping, not NVIDIA's full support matrix. `mmartial` has configured `cu126` and `cu128` images; other CUDA selections fall back to its `cu126` image. `yanwk` has configured `cu118`, `cu126`, `cu128`, and `cu130` images. See `airpods/cuda.py` and `airpods/comfyui.py` for exact mappings/tags and [ComfyUI](../services/comfyui.md) for provider-specific mounts.

## CPU and Passthrough

- `airpods start --cpu` forces CPU execution and selects CPU service images for the invocation, including `--pre-fetch`.
- `runtime.cuda_version = "cpu"` disables GPU use globally.
- `services.<name>.gpu.force_cpu = true` or `gpu.enabled = false` disables GPU use for that service.
- Missing GPU hardware or runtime passthrough causes startup to select CPU behavior. ComfyUI uses the `yanwk` CPU image; llama.cpp uses `:server`.

GPU detection alone does not prove passthrough works. `doctor` checks NVIDIA Container Toolkit/CDI availability and prints remediation. Verify `nvidia-smi` and the selected container runtime setup when GPU startup fails.
