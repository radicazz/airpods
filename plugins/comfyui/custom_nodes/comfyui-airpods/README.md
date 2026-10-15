# ComfyUI AirPods Tools

Custom nodes that connect ComfyUI to local llama.cpp and Ollama HTTP APIs.

## Setup

Run `airpods start comfyui llamacpp --wait` for llama.cpp nodes, or `airpods start comfyui ollama --wait` for Ollama nodes. Airpods syncs this package automatically. After syncing into an already-running ComfyUI, stop/start ComfyUI to load changed nodes.

Choose an AirPods node in ComfyUI, provide its prompt/chat inputs, and connect the `text` output downstream. Ollama nodes also require an installed Ollama model. Embedding nodes are not implemented.

Set the environment variables below in `[services.comfyui.env]` when backend ports differ from the defaults. Both services use host networking, so the defaults use `localhost`.

## Nodes

### Llama (OpenAI-style API)

- Llama Text Completion (AirPods)
- Llama Chat Completion (AirPods)

### Ollama (native API)

- Ollama Generate (AirPods)
- Ollama Chat (AirPods)

### Text Utilities

- Text Combine (AirPods)
- Text Repeat (AirPods)

## Environment Variables

### llama.cpp

- `AIRPODS_LLAMACPP_URL` (default: `http://localhost:11435/v1`)
- `AIRPODS_LLAMACPP_TIMEOUT` (default: `120` seconds)

### Ollama

- `AIRPODS_OLLAMA_URL` (default: `http://localhost:11434`)
- `AIRPODS_OLLAMA_TIMEOUT` (default: `120` seconds)

Each backend node also accepts a `base_url` input that overrides the env var.

## Notes

- Streaming is disabled; set `stream = false` for Ollama requests.
- `messages_json` and `options_json` inputs must be valid JSON.
- `raw_json` output returns the full response for debugging.

## Quick Examples

### Llama Chat

```json
{
  "messages": [
    { "role": "system", "content": "You are concise." },
    { "role": "user", "content": "Explain KV cache in one paragraph." }
  ],
  "max_tokens": 256,
  "temperature": 0.7,
  "top_p": 0.95
}
```

### Ollama Generate

```json
{
  "model": "llama3.1:8b",
  "prompt": "Write a two sentence summary of GGUF.",
  "stream": false,
  "options": { "temperature": 0.7, "top_p": 0.95 }
}
```
