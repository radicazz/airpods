# docs/goals

## Purpose

- Provide a small, focused CLI that orchestrates local AI services (Ollama, Open WebUI, ComfyUI, and supporting components) rather than becoming a service or UI itself.
- Make it easy to spin these services up and down in a secure, maintainable, and reproducible way on a single machine.

## What Airpods Should Do

- Manage containers and pods for:
  - Ollama as the local model runtime.
  - Open WebUI as a ready‑made chat and management UI.
  - ComfyUI as a workflow / graph UI.
  - Caddy as a reverse proxy and TLS terminator.
  - An optional file / notebook server (e.g. Jupyter or similar) for working with artifacts and data.
- Provide simple, predictable lifecycle commands (`start`, `stop`, `status`, `logs`, `doctor`, `config`, and `clean`) with optional `start --pre-fetch` support for warming images ahead of time. These commands must:
  - Create and reuse volumes for persistent data.
  - Wire services together correctly (ports, networks, secrets, GPU access).
  - Fail with clear, actionable error messages when dependencies or containers are misconfigured.

## What Airpods Is Not

- It is not a replacement for Open WebUI or ComfyUI; those projects own their UI/feature surface.
- It is not a hosted platform or multi‑tenant service; the focus is on local developer/creator environments.

## Design Priorities

- Prefer configuration and templates (TOML + runtime resolution) over hard‑coding service details.
- Keep commands safe by default (non‑destructive `start`, explicit `clean` for destructive actions).
- Optimize for clarity and reproducibility: a new user should be able to go from zero to a working stack with a small number of documented commands.
