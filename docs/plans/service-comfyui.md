# docs/plans/service-comfyui

**STATUS:** IMPLEMENTED (v0.5.0) - Service enabled by default using yanwk/comfyui-boot community image

## Purpose

- Add ComfyUI as an optional, Podman-managed service focused on composable diffusion workflows, while keeping airpods responsible for orchestration (pods, volumes, networks, config).
- Expose ComfyUI’s backend (queue + websockets) and workflow APIs so other services (Open WebUI plugins, pipelines, future UIs) can run image/video/audio jobs without modifying the airpods CLI.
- Enable safe sharing of models, custom nodes, and workflows across services via controlled volumes and network access, with gateway-level authentication when exposed.

## Role In The Stack

- Runs as a service (`comfyui`) managed by `start/stop/status/logs` (with `start --pre-fetch` available for ahead-of-time image pulls), attached to the same user-defined Podman network as Ollama, Open WebUI, and llama.cpp.
- Serves two surfaces:
  - **Frontend UI** for interactive graph editing and execution.
  - **Backend API**: HTTP queue + websocket status/preview channels for programmatic workflow submission.
- Access pattern:
  - Default: internal-only network; exposed to other services via the Podman network alias (`comfyui`).
  - When the gateway is enabled, Caddy can front ComfyUI if host access is needed; otherwise keep it internal and reach it from Open WebUI plugins.
- Artifact sharing:
  - Models and workflows live on mounted volumes and are intended to be shared read-only with other services; writes stay within ComfyUI.

## Backend & API Surface (current upstream behavior)

- **Queue HTTP API**: POST a workflow graph to `/prompt` to enqueue; returns a prompt/workflow ID.
- **Websocket**: `/ws` (default) streams execution updates, node status, progress, previews.
- **Workflow I/O**: Workflows saved/loaded as JSON; can be embedded in generated PNG/metadata.
- **Model paths**: Configurable via `extra_model_paths.yaml` and directory layout under `models/` (checkpoints, VAEs, LoRAs, embeddings, control nets, etc.).
- **Custom nodes**: Python modules placed in `custom_nodes/`; extend server runtime.
- **Execution**: Asynchronous queue, incremental re-execution of changed nodes, GPU/CPU support (offloading available).

## Integration Patterns With Airpods Services

- **Open WebUI plugins**: Functions/Tools can submit workflows to ComfyUI via HTTP + websocket, then return result URLs back to chat. Use internal network aliases (e.g., `http://comfyui:8188`) to avoid bypassing gateway auth.
- **llama.cpp / Ollama**: Generated images or embeddings from ComfyUI can be referenced in chat responses or fed into downstream pipelines managed by Open WebUI plugins or future portal endpoints.
- **Shared storage**:
  - Mount a dedicated volume for ComfyUI models/workflows (e.g., `airpods_comfyui_models`) and, when safe, expose read-only subpaths to other services (Ollama/llama/Open WebUI plugins) that need to read artifacts. Writes stay in ComfyUI.
  - Keep custom nodes isolated to the ComfyUI container; avoid executing arbitrary node code from other services.
- **Gateway**:
  - Use Caddy to expose ComfyUI’s UI/API on a single authenticated port when needed.
  - For internal-only automation, skip host binds and call via the Podman network.

## Configuration & Deployment Notes

### Current Implementation (v0.5.0+)

- **Image**: `docker.io/yanwk/comfyui-boot:cu128-slim`
  - Community-maintained image with CUDA 12.8, Python 3.12
  - Includes ComfyUI + ComfyUI-Manager out of the box
  - Alternative to build your own: future plan is to fork and customize
  - Other variants: `cu126-slim`, `cu128-megapak`, `rocm`, `xpu`, `cpu`
- **Port**: `8188` (ComfyUI standard) mapped to host
- **Volume**: `airpods_comfyui_models` → `/root/ComfyUI/models`
- **GPU**: Auto-detected and enabled; CPU fallback available
- **Health**: HTTP check on `/`
- **Network**: Internal alias `comfyui` for service-to-service calls

### Legacy Documentation

- **Service spec (illustrative shape)**:
  - Image: ComfyUI official container (GPU/CPU variant per host).
  - Ports: default UI/API port `7860` mapped to host only when gateway is disabled; otherwise internal-only.
  - Volumes:
    - `airpods_comfyui_models` → `/models` (checkpoints, VAEs, LoRAs, control nets, etc.).
    - `airpods_comfyui_workflows` → `/workflows` (JSON workflows, outputs).
    - Optional bind for `custom_nodes` if users opt in.
  - GPU: enable if available; otherwise allow CPU with explicit flag.
  - Health: HTTP check on `/` (UI) or a lightweight API probe; account for model scan startup time.
- **Paths & sharing**:
  - Document which subdirectories can be safely shared read-only with other services (e.g., `workflows/` exports) versus write-only (outputs).
  - Avoid mounting ComfyUI’s `custom_nodes` into other services to reduce risk.
- **Security**:
  - No built-in auth by default; rely on gateway Basic Auth (or future auth) when exposing the UI/API.
  - Keep the service on the internal network by default; host binds only when the user opts in.

## Utility As A Service

- Provides a powerful, node-based workflow engine for image/video/audio generation and editing without altering airpods core.
- Programmatic API lets Open WebUI plugins or other clients submit jobs, monitor progress, and retrieve outputs, turning ComfyUI into a shared generation backend.
- Shared volumes allow models/workflows to persist across updates and be reused in automation pipelines, with controlled read/write policies.

## Interaction With Other Plans

- **service-open-webui**: Open WebUI plugins can call ComfyUI over the internal network; consider documenting the ComfyUI alias/port in Open WebUI admin notes so plugin authors can target it.
- **service-gateway**: Gateway can front ComfyUI to add Basic Auth/TLS; ComfyUI itself remains internal when gateway is enabled.
- **service-llama**: Image outputs from ComfyUI can be referenced in chat or fed into multimodal pipelines; sharing is via URLs or shared volumes, not direct code execution.
- **Shared artifacts**: When multiple services need access to the same models or outputs, prefer read-only mounts or explicit export directories to avoid accidental mutation.

## Implementation Reminders (non-binding)

- Keep ComfyUI optional and config-driven; do not auto-install custom nodes.
- Provide a single network alias (`comfyui`) and surface it in `status` so other services know where to call.
- Default posture: internal-only network, gateway for host exposure, Basic Auth if exposed.
- Make volume layout explicit (models/workflows/outputs) and flag which paths are safe for read-only sharing.
- Account for slower startup when scanning models/custom nodes; allow configurable startup timeout/health retries.

## Summary

- ComfyUI becomes an optional, orchestrated service that delivers a graph-based diffusion backend with an HTTP queue and websocket status channel.
- Airpods handles lifecycle, networking, volumes, and (via the gateway) outer auth; ComfyUI handles workflows, models, and custom nodes.
- Other services (Open WebUI plugins, pipelines, future portals) can safely call ComfyUI over the internal network, reuse shared artifacts via controlled volumes, and expose results to users without modifying airpods core.
