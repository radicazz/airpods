# docs/plans/custom_node_llama

**STATUS:** IMPLEMENTED (merged into comfyui-airpods)

## Purpose

Provide ComfyUI nodes that talk to the llama.cpp OpenAI-compatible HTTP API, enabling GGUF models to be used inside ComfyUI workflows without `llama-cpp-python`.

This plan is now merged into a single custom-node package that also includes Ollama nodes:
`plugins/comfyui/custom_nodes/comfyui-airpods/`.

## Package Layout

- Path: `plugins/comfyui/custom_nodes/comfyui-airpods/`
- Files:
  - `__init__.py` (exports node mappings)
  - `nodes.py` (node implementations for llama.cpp + Ollama)
  - `client.py` (minimal HTTP client wrapper)
  - `README.md` (usage + environment variables)

## Service Discovery

- Base URL env var: `AIRPODS_LLAMACPP_URL`
  - Default: `http://localhost:11435/v1`
- Timeout env var: `AIRPODS_LLAMACPP_TIMEOUT`
  - Default: `120` (seconds)

The nodes allow overriding the base URL per-node input as well, with the env var as the default.

## Node Set (llama.cpp)

### 1) Llama Text Completion

- **Name**: `LlamaTextCompletion`
- **Purpose**: `/v1/completions` for classic prompt completion
- **Inputs**:
  - `prompt` (string)
  - `max_tokens` (int, default 256)
  - `temperature` (float, default 0.7)
  - `top_p` (float, default 0.95)
  - `stop` (string or list, optional)
  - `seed` (int, optional)
  - `model` (string, optional; if omitted, llama.cpp default is used)
  - `base_url` (string, optional)
- **Outputs**:
  - `text` (string)
  - `raw_json` (string; compact JSON for debugging)

### 2) Llama Chat Completion

- **Name**: `LlamaChatCompletion`
- **Purpose**: `/v1/chat/completions`
- **Inputs**:
  - `system` (string, optional)
  - `user` (string)
  - `max_tokens` (int, default 256)
  - `temperature` (float, default 0.7)
  - `top_p` (float, default 0.95)
  - `stop` (string or list, optional)
  - `seed` (int, optional)
  - `model` (string, optional)
  - `base_url` (string, optional)
- **Outputs**:
  - `text` (string)
  - `raw_json` (string)

Note: For advanced workflows, support a JSON `messages` input (list of `{role, content}`) as an optional alternate input. If provided, it supersedes `system` + `user`.

### 3) Llama Embeddings (Deferred)

- **Name**: `LlamaEmbeddings`
- **Purpose**: `/v1/embeddings`
- **Inputs**:
  - `input` (string or list of strings)
  - `model` (string, optional)
  - `base_url` (string, optional)
- **Outputs**:
  - `embeddings` (list of lists of floats)
  - `raw_json` (string)

## HTTP Client Behavior

- Use Python stdlib `http.client` or `requests` (prefer stdlib to avoid dependency issues).
- Always set `Content-Type: application/json`.
- Timeout: `AIRPODS_LLAMACPP_TIMEOUT` (default 120 seconds).
- Errors:
  - Non-2xx responses raise a friendly error with status + excerpt of response text.
  - Connection failures show a hint to check `airpods start llamacpp` and the URL.

## Example Requests

Text completion:

```json
{
  "model": "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
  "prompt": "Write a two sentence summary of GGUF.",
  "max_tokens": 128,
  "temperature": 0.7,
  "top_p": 0.95
}
```

Chat completion:

```json
{
  "model": "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
  "messages": [
    { "role": "system", "content": "You are concise." },
    { "role": "user", "content": "Explain KV cache in one paragraph." }
  ],
  "max_tokens": 256,
  "temperature": 0.7
}
```

Embeddings:

```json
{
  "model": "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
  "input": ["hello", "world"]
}
```

## ComfyUI Registration

`__init__.py` should export:

- `NODE_CLASS_MAPPINGS` with `LlamaTextCompletion`, `LlamaChatCompletion` (embeddings deferred)
- `NODE_DISPLAY_NAME_MAPPINGS` with friendly names like:
  - `"Llama Text Completion (AirPods)"`
  - `"Llama Chat Completion (AirPods)"`

## Packaging + Sync

- The `airpods start` workflow should sync `plugins/comfyui/custom_nodes/comfyui-airpods/` into the `comfyui_custom_nodes` bind mount (consistent with other plugin sync).
- The node package contains no compiled binaries and should run in the base ComfyUI image.

## Testing Plan

- Unit tests for `client.py` with mocked HTTP responses.
- Basic integration test by running ComfyUI + llama.cpp locally and confirming node outputs.
- Negative tests for connection refusal and non-2xx responses.

## Summary

These nodes provide a simple, dependency-light bridge from ComfyUI to llama.cpp’s OpenAI-compatible API, enabling GGUF LLM workflows without Python bindings inside the ComfyUI container.
