# docs/goals

## Purpose

Provide a focused CLI for running local AI services on one machine. Airpods manages containers, configuration, persistent data, GPU access, and readiness; Ollama, llama.cpp, Open WebUI, and ComfyUI provide inference and user interfaces.

## Current Scope

- Support Podman and Docker through the same lifecycle commands.
- Create and reuse service resources while preserving user data.
- Manage Ollama models, shared GGUF files, and ComfyUI workflow/model downloads.
- Sync bundled plugins and install configured ComfyUI custom nodes.
- Back up configuration, WebUI state, and model metadata without copying large model binaries.
- Report actionable errors when runtime, GPU, model, or configuration requirements are unmet.

## Design Priorities

- Prefer TOML configuration and templates over hard-coded service details.
- Keep resource reuse predictable and destructive actions explicit.
- Keep documentation clear about implemented behavior versus proposals.
- Preserve a small CLI; upstream services own their interfaces. A hosted platform, multi-tenant service, and custom web portal are outside the current scope.

An optional reverse proxy remains a [future proposal](plans/service-gateway.md). Caddy and notebook/file servers are not shipped services. See [the roadmap](../TODO.md) for outstanding work.
