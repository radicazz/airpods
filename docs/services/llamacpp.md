# docs/services/llamacpp

The enabled-by-default `llamacpp` service runs a GGUF model through llama.cpp's HTTP server. Aliases are `llama`, `llama-cpp`, and `llama.cpp`.

```bash
airpods start llamacpp --wait
airpods status llamacpp
airpods logs llamacpp
airpods stop llamacpp
```

The default URL is `http://localhost:11435`; `/health` supplies readiness. CPU uses `ghcr.io/ggml-org/llama.cpp:server`, while GPU startup selects `:server-cuda` when passthrough is available. `--cpu` forces CPU execution. `--wait` uses the configured startup timeout, including model loading time.

## Models and Arguments

GGUF files live in `<state-root>/volumes/airpods_models/gguf/`, mounted at `/models`. The built-in default is `Qwen3.5-4B-heretic-Q4_K_M.gguf` from [saidutta69/Qwen3.5-4B-heretic](https://huggingface.co/saidutta69/Qwen3.5-4B-heretic). Existing configuration overrides remain in effect. Startup offers to download the configured default model when missing; `--yes` accepts that download. For another model:

```bash
airpods stop llamacpp
airpods gguf pull https://example.com/model.gguf --name my-model.gguf
airpods config set services.llamacpp.default_model my-model.gguf
airpods config set services.llamacpp.default_model_url '' --type str
airpods start llamacpp --wait
```

Replace the example URL with a direct GGUF download URL. Clearing `default_model_url` prevents startup from fetching the previous default under the new filename if your model is missing. If the service is already running, stop it before starting with a different model or configuration.

The default model argument follows `default_model` through a template. Configure server arguments as a mapping:

```toml
[services.llamacpp.command_args]
model = "/models/{{services.llamacpp.default_model}}"
ctx_size = 4096
n_gpu_layers = 40
threads = 8
port = "{{services.llamacpp.ports.0.host}}"
host = "0.0.0.0"
```

Keys become kebab-case flags (`ctx_size` → `--ctx-size`). True booleans produce a flag, false booleans omit it, lists repeat the flag, and other values become separate arguments. Arguments are passed without shell interpolation. `entrypoint_override` can replace `/app/llama-server`.

## Multiple Models

Airpods starts llama.cpp with one explicit `--model`. Keeping multiple GGUF files in the store does not make them selectable in the built-in llama.cpp UI. Use the stop/configure/start sequence above to switch the served model.

Upstream [llama.cpp router mode](https://github.com/ggml-org/llama.cpp/tree/master/tools/server#using-multiple-models) supports loading different models on demand and routing API requests by model name. It requires starting without `--model`, with `--models-dir /models` for this store; the built-in UI supports model selection in router mode. Airpods 0.26.1 keeps its single-model default. Using models simultaneously also requires enough RAM/VRAM; separate server instances need distinct host ports and container/pod names.

## Clients and Persistence

In Open WebUI's connection settings, add an OpenAI-compatible connection pointing to `http://localhost:11435/v1`. Both services share the host network; changing the server port requires updating this URL. Airpods' `auto_configure_ollama` setting configures Ollama, so configure the llama.cpp connection separately.

The bundled [ComfyUI nodes](../../plugins/comfyui/custom_nodes/comfyui-airpods/README.md) use the same `/v1` endpoint. Stop/start preserves GGUF files; `state clean --volumes` removes configured bind-mounted data. Backups include non-GGUF files from this store, so keep model binaries separately or download them again.
