# docs/plans/service-open-webui

**STATUS:** IMPLEMENTED (v0.4.0) - Core service with plugin extensibility

## Purpose

- Keep Open WebUI as the primary user-facing chat/management UI within airpods, but document how its built-in Tools/Functions/Pipelines plugin system can connect to other airpods-managed services (Ollama, llama.cpp, ComfyUI, future runtimes) using full Python runtimes inside plugins.
- Make plugin-driven extensibility a first-class, optional capability: admins can import community plugins or write their own to wire external services, add UI actions, or expose new APIs, without changing airpods core.
- Align with `docs/goals.md`: airpods remains the orchestrator (pods, volumes, configs); Open WebUI is an opt-in UI layer that can be extended through plugins rather than forking the UI.

## Role In The Stack

- Runs as an optional Podman service (`open-webui`) managed by `start/stop/status/logs` (with `start --pre-fetch` available for pre-downloading images).
- Serves the chat UI and admin panel; it is the only host-facing service by default. When the gateway is enabled, it sits behind Caddy on a single port; otherwise it can bind directly to the host.
- Plugins (Tools, Functions, Pipelines) execute inside Open WebUI’s Python runtime and can call other services on the Podman network (`host.containers.internal`, network aliases) or the public internet, depending on configuration.
- Best suited as the “integration surface” where user actions and LLM calls can reach other managed services without modifying the airpods CLI.

## Plugin Surface (from Open WebUI docs)

- **Tools**: give LLM conversations new abilities to fetch real-world data (e.g., weather, stocks) or call external APIs; imported from the community with one click; configured per workspace.
- **Functions**: extend Open WebUI itself (add model backends like Anthropic/Vertex, add UI buttons/filters, alter behavior). Managed in the Admin Panel.
- **Pipelines**: advanced; transform Open WebUI features into OpenAI API–compatible workflows for heavy/offloaded processing.
- Admin vs user scope: Tools are user/workspace-scoped; Functions are admin-scoped.

## Integration Patterns With Airpods Services

- **Ollama / llama.cpp backends**: Use Functions to register additional model providers that target the local OpenAI-style endpoints airpods exposes (`http://host.containers.internal:<port>/v1`). This enables side-by-side backends and model routing without changing airpods service specs.
- **ComfyUI or image services**: Tools/Functions can call internal HTTP endpoints (e.g., a ComfyUI workflow API) to render images, then return URLs/attachments back into chat. The plugin code runs in Python, so it can orchestrate requests, poll jobs, and post-process results.
- **Gateway-aware URLs**: When the gateway is enabled, plugins should call internal service aliases (Podman network names) rather than host ports to avoid bypassing auth. Network aliases are configured at the pod level and shared by all containers in that pod. Available aliases: `open-webui` (or `webui`), `ollama`, `comfyui`, `gateway` (when implemented).
- **Volume/secret access**: Plugins can read files only if Open WebUI is configured with the necessary mounts; for safety, prefer HTTP calls to services that already have access to their own volumes. Shared artifacts (models, workflows, outputs) should be accessed read-only unless a service explicitly owns the write path.
- **Pipelines for orchestration**: For heavy or batched tasks (e.g., chaining RAG → image gen → narration), Pipelines can wrap multiple Tools/Functions into an OpenAI-compatible flow that external clients can call via the Open WebUI API.

## Configuration & Deployment Notes

- Service definition follows existing `open-webui` config (image, ports, volumes, env, health). Plugins are managed inside the running app; airpods does not ship or update plugins.
- Network: ensure Open WebUI shares the user-defined Podman network with Ollama, llama.cpp, ComfyUI so plugin HTTP calls resolve via service aliases.
- Admin setup: enable Functions/Tools/Pipelines in the Admin Panel; import plugins from the community or mount custom ones into Open WebUI’s plugin directory if desired (managed manually or via future helper scripts).
- Security: when gateway auth is enabled, keep Open WebUI internal-only; plugins that need external internet should be reviewed, as they execute code in the server runtime.

## Utility As A Service

- Gives airpods users a high-level UI that can be extended without touching the CLI:
  - Add new model backends (Functions) pointing at local or remote OpenAI-compatible endpoints.
  - Add Tools that call other airpods services (RAG stores, image generators, pipelines) with Python logic.
  - Build Pipelines that expose compound workflows as OpenAI-compatible APIs for automation clients.
- Makes airpods’ other services “pluggable” into chat and admin experiences through Open WebUI’s runtime, turning the UI into a hub for local orchestration.

## Interaction With Other Plans

- **Gateway**: Gateway adds outer auth/TLS; Open WebUI keeps its own auth. Plugins should prefer internal service aliases so traffic stays on the private network. If Basic Auth is enabled on the gateway, end users may see gateway auth + Open WebUI login.
- **llama.cpp service**: When llama.cpp runs as an OpenAI-style backend, Functions can register it as a provider so users can pick models from it inside Open WebUI.
- **Future airpods-webui/portal**: If a first-party UI replaces Open WebUI, this document still applies while Open WebUI remains an optional service; plugins are contained within Open WebUI’s runtime and do not alter airpods core.

## Implementation Reminders (non-binding)

- Keep Open WebUI service optional and configuration-driven; do not bake plugin installs into `airpods start --pre-fetch`/`airpods start`.
- Provide network aliases and port info in status output so plugin authors know the internal endpoints to call.
- Document a safe default: gateway on (internal Open WebUI) + optional Basic Auth; Open WebUI’s own auth remains primary for user accounts.
- Avoid auto-mounting arbitrary plugin directories by default; let admins opt in to custom plugin mounts if needed.

## Summary

- Open WebUI remains the extensible UI layer for airpods. Its Tools/Functions/Pipelines plugins (Python runtime) let admins wire local services (Ollama, llama.cpp, ComfyUI, others) and external APIs directly into chat and admin flows.
- Airpods keeps orchestration concerns (pods, volumes, networks, secrets); Open WebUI plugins provide the integration logic and UI affordances, making the stack more powerful without modifying the CLI or service definitions.
