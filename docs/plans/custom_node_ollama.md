# docs/plans/custom_node_ollama

**STATUS:** IMPLEMENTED (merged into comfyui-airpods)

## Quick Answer: API Style

Ollama exposes its own HTTP API by default (e.g., `/api/generate`, `/api/chat`, `/api/embeddings`). It is not identical to the OpenAI-style API used by llama.cpp. This plan targets the native Ollama API. If you want to support OpenAI-style endpoints as an option, add a toggle later, but it is not required to ship a useful node.

## Purpose

Provide ComfyUI nodes that talk to a local Ollama instance over HTTP so models pulled by Ollama can be used inside ComfyUI workflows.

This plan is now merged into a single custom-node package that also includes llama.cpp nodes:
`plugins/comfyui/custom_nodes/comfyui-airpods/`.

## Package Layout

- Path: `plugins/comfyui/custom_nodes/comfyui-airpods/`
- Files:
  - `__init__.py` (exports node mappings)
  - `nodes.py` (node implementations for llama.cpp + Ollama)
  - `client.py` (minimal HTTP client wrapper)
  - `README.md` (usage + environment variables)

## Service Discovery

- Base URL env var: `AIRPODS_OLLAMA_URL`
  - Default: `http://localhost:11434`
- Timeout env var: `AIRPODS_OLLAMA_TIMEOUT`
  - Default: `120` (seconds)

The nodes allow overriding the base URL per-node input as well, with the env var as the default.

## Node Set

### 1) Ollama Generate (Text)

- **Name**: `OllamaGenerate`
- **Purpose**: `/api/generate` for prompt completion
- **Inputs**:
  - `model` (string, required; e.g., `llama3.1:8b`)
  - `prompt` (string)
  - `system` (string, optional)
  - `options_json` (string, optional; JSON string forwarded to `options`)
  - `format` (string, optional; e.g., `json`)
  - `stream` (bool, default false; node returns full output)
  - `base_url` (string, optional)
- **Outputs**:
  - `text` (string)
  - `raw_json` (string)

### 2) Ollama Chat

- **Name**: `OllamaChat`
- **Purpose**: `/api/chat` for chat-style completion
- **Inputs**:
  - `model` (string, required)
  - `system` (string, optional)
  - `user` (string)
  - `messages_json` (string, optional; JSON list of `{role, content}`)
  - `options_json` (string, optional)
  - `format` (string, optional)
  - `stream` (bool, default false)
  - `base_url` (string, optional)
- **Outputs**:
  - `text` (string)
  - `raw_json` (string)

If `messages_json` is provided, it supersedes `system` + `user`.

### 3) Ollama Embeddings (Deferred)

- **Name**: `OllamaEmbeddings`
- **Purpose**: `/api/embeddings`
- **Inputs**:
  - `model` (string, required)
  - `input` (string or list of strings)
  - `base_url` (string, optional)
- **Outputs**:
  - `embeddings` (list of lists of floats)
  - `raw_json` (string)

## HTTP Client Behavior

- Use Python stdlib `http.client` to avoid extra dependencies.
- Always set `Content-Type: application/json`.
- Timeout: `AIRPODS_OLLAMA_TIMEOUT` (default 120 seconds).
- Errors:
  - Non-2xx responses raise a friendly error with status + excerpt of response text.
  - Connection failures show a hint to check `airpods start ollama` and the URL.

## Example Requests

Generate:

```json
{
  "model": "llama3.1:8b",
  "prompt": "Write a two sentence summary of GGUF.",
  "system": "You are concise.",
  "stream": false,
  "options": { "temperature": 0.7, "top_p": 0.95 }
}
```

Chat:

```json
{
  "model": "llama3.1:8b",
  "messages": [
    { "role": "system", "content": "You are concise." },
    { "role": "user", "content": "Explain KV cache in one paragraph." }
  ],
  "stream": false,
  "options": { "temperature": 0.7 }
}
```

Embeddings:

```json
{
  "model": "nomic-embed-text",
  "input": ["hello", "world"]
}
```

## ComfyUI Registration

`__init__.py` should export:

- `NODE_CLASS_MAPPINGS` with `OllamaGenerate`, `OllamaChat` (embeddings deferred)
- `NODE_DISPLAY_NAME_MAPPINGS` with friendly names like:
  - `"Ollama Generate (AirPods)"`
  - `"Ollama Chat (AirPods)"`

## Packaging + Sync

- The `airpods start` workflow should sync `plugins/comfyui/custom_nodes/comfyui-airpods/` into the `comfyui_custom_nodes` bind mount (consistent with other plugin sync).
- The node package contains no compiled binaries and should run in the base ComfyUI image.

## Testing Plan

- Unit tests for `client.py` with mocked HTTP responses.
- Basic integration test by running ComfyUI + Ollama locally and confirming node outputs.
- Negative tests for connection refusal and non-2xx responses.

## Summary

These nodes provide a dependency-light bridge from ComfyUI to the Ollama native HTTP API, enabling Ollama-hosted models to be used in workflows without embedding Ollama into the ComfyUI image.
