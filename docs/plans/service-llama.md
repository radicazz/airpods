# docs/plans/service-llama

**STATUS:** PLANNED - NOT IMPLEMENTED (requires `command_args` schema extension)

## Purpose

- Add llama.cpp as an optional, first-class service in airpods alongside Ollama, Open WebUI, ComfyUI, and supporting components.
- Use llama.cpp to provide a flexible, local LLM runtime with GGUF models, OpenAI-style HTTP APIs, and both CPU and GPU execution paths.
- Keep airpods focused on orchestration: containers, pods, volumes, networks, and configuration; llama.cpp remains the model runtime, not a replacement UI.

## Role In The Stack

- Runs as an additional Podman-managed service that airpods can `start`, `stop`, `status`, and `logs` (with `start --pre-fetch` available for warming images), just like Ollama and Open WebUI.
- Exposes an OpenAI-compatible HTTP API (via `llama-server`) that Open WebUI can use as a backend through its OpenAI connection settings.
- Optionally exposes the native llama.cpp WebUI (SvelteKit-based) for lightweight, local-only chat and model management.
- Stores GGUF models on a dedicated volume so they persist across container restarts and can be reused by different llama.cpp instances.
- Model artifacts are intended to be shared read-only with other services (e.g., Open WebUI plugins, ComfyUI consumers) via mounts or download links; by default, keep the llama model volume private and only expose what’s needed to avoid accidental mutation.

## Capabilities (From Existing Plan)

- Uses GGUF model format with quantization (Q2–Q8 / Q2_K, Q4_K_M, Q5_K_M, Q8_0) to reduce memory usage substantially at modest accuracy cost.
- Provides an OpenAI-style HTTP interface via `llama-server`, including `/v1/chat/completions`, `/v1/completions`, and `/v1/embeddings`.
- Supports CPU-first execution and optional GPU acceleration depending on image variant and flags.
- Offers tooling around:
  - Interactive CLI chat (`llama-cli`).
  - HTTP server mode (`llama-server`).
  - Conversion and quantization utilities for GGUF models.
  - Native WebUI (SvelteKit) for chat, document uploads, vision-capable models, parameter tuning, and model switching (as described in the existing plan).

## Service Shapes Described So Far

The current private plan describes three main ways to run llama.cpp under airpods:

- OpenAI-compatible backend for Open WebUI:
  - Service name: `llamacpp`.
  - Runs a `llama-server` container exposing HTTP endpoints for OpenAI-style APIs.
  - Open WebUI connects to this service using its OpenAI connection settings (e.g., pointing to the service’s `/v1` endpoint).
- Standalone service with native WebUI:
  - Service name: `llamacpp-ui`.
  - Uses the same underlying server but relies on the built-in WebUI to provide a minimal chat and model management interface.
  - Exposes the WebUI over HTTP while still offering the same HTTP API.
- Hybrid / multi-backend layouts:
  - Run Ollama and llama.cpp simultaneously, with Open WebUI configured to talk to both backends.
  - Use separate llama.cpp instances with different models or configurations (e.g., a fast chat-oriented instance vs a large-context instance), each bound to its own port.

All of these are expressed as TOML service entries under `[services.*]` with fields such as `image`, `pod`, `container`, `network_aliases`, `ports`, `volumes`, `gpu`, `health`, `env`, `resources`, and `command_args` in the existing plan.

## Configuration Patterns (As Described)

- Services are defined under `services.llamacpp` and `services.llamacpp-ui` with:
  - `image` values pointing at llama.cpp images (CPU or GPU-oriented variants).
  - `pod`/`container` names and `network_aliases` so other services (like Open WebUI) can reach them.
  - `ports` mapping a host port to the container’s HTTP port.
  - `volumes` mapping a persistent volume (e.g., `airpods_llamacpp_models`) into `/models` inside the container so GGUF files persist.
  - `gpu` configuration with `enabled` / `force_cpu` flags.
  - `health` checks using HTTP paths described in the plan (e.g., `/health` for the API, `/` for the UI) and expected status ranges.
  - Optional `resources` fields (such as memory/CPU limits) when needed.
- Command-line arguments are described as `command_args`:
  - Represented as a mapping from option names (like `model`, `ctx_size`, `threads`, `n_gpu_layers`, `batch_size`, `port`, `host`) to values.
  - Intended to be rendered into CLI flags for `llama-server` (for example, `model = "/models/{{default_model}}"` becoming a `--model` flag after template resolution).
  - Template placeholders (for example `{{default_model}}`) are expected to be resolved using the existing airpods configuration template mechanism.

The private plan proposes extending the service schema to support these `command_args` and describes helper logic for building the final container command from this mapping.

## How It Serves Airpods Goals

- Fits the “orchestrate local AI services” purpose:
  - llama.cpp adds another local model backend that airpods can manage via Podman, alongside Ollama and future runtimes.
  - Airpods remains a thin, focused CLI; llama.cpp provides the inference engine and, optionally, its own UI.
- Works with the existing lifecycle model:
  - `start` creates the llama.cpp model volume(s), pulls images, brings up the pods/containers, waits for their HTTP health checks, and reports readiness.
  - `start --pre-fetch` can warm caches by downloading llama.cpp images without starting containers.
  - `stop` shuts down pods cleanly while preserving model volumes.
  - `status` shows each llama-related service (backend and optional UI) with basic HTTP health and URLs.
  - `logs` tails the llama.cpp containers for debugging or monitoring model loads and requests.
- Respects configuration-first design:
  - Service details, images, ports, and command arguments are all described in TOML and can be templated, rather than hard-coded in commands.
  - Users can point llama.cpp at different GGUF models or adjust parameters (context size, threads, GPU layer usage) by editing config rather than modifying code.

## Utility As A Service

- Enables alternative and complementary model runtimes:
  - Users can keep Ollama as a convenient multi-model backend while using llama.cpp for power-user control, quantization experiments, or CPU-focused workloads, as described in the existing plan.
  - Open WebUI can be configured to target llama.cpp’s OpenAI-style API endpoints, allowing side-by-side comparisons and different backends per workspace.
- Supports diverse hardware:
  - The plan explicitly calls out CPU-only setups and GPU-accelerated setups, using image variants and command flags to adapt to the available hardware.
  - Quantized GGUF models make it practical to run larger models on constrained machines, aligning with airpods’ goal of working well on a single local host.
- Offers multiple UX options:
  - For users who prefer a minimal interface, the llama.cpp native WebUI described in the plan can provide a lightweight alternative to Open WebUI.
  - For users who want a richer, multi-backend experience, the Open WebUI + llama.cpp backend arrangement remains available.

## Implementation Notes (From The Existing Plan)

- The private plan proposes:
  - Adding schema support for `command_args` (and potentially an `entrypoint_override`) so services like llama.cpp that are configured via CLI flags can be expressed declaratively in config.
  - Implementing helper logic to render `command_args` into a final command array, including template resolution.
  - Selecting llama.cpp images based on GPU detection (e.g., CPU vs CUDA vs ROCm variants), using the existing GPU detection utilities.
  - Extending startup behavior for llama.cpp services to account for model load time, using the configured health endpoints and timeouts.
- Testing suggestions in the plan include:
  - Unit tests for config rendering (especially `command_args`) and image selection.
  - Mocked tests around service start behavior and health probing.
  - Manual checks (and, optionally, heavier integration tests) for successful startup, HTTP health, WebUI access, and Open WebUI connectivity.

## Summary

- llama.cpp can be added as an optional service that:
  - Uses the same Podman- and config-driven patterns as existing services.
  - Exposes an OpenAI-style HTTP API and, optionally, its own WebUI.
  - Stores models in persistent volumes using GGUF format and quantization.
  - Runs on CPU or GPU, configured through TOML and templates.
- This makes llama.cpp another building block in the airpods stack, giving users more control over model runtimes while keeping airpods focused on orchestration rather than becoming a model runtime or UI itself.
