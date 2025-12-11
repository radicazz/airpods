# docs/plans/service-gateway

**STATUS:** PLANNED - NOT IMPLEMENTED

## Purpose

- Add an optional Caddy-based gateway service that sits in front of existing web UIs (initially Open WebUI, later airpods-webui + portal) to provide a single HTTP entrypoint with basic authentication.
- Use the same `AIRPODS_HOME`-driven layout and Podman orchestration that airpods uses for other services, so the gateway is configured and managed like the rest of the stack.
- Keep airpods focused on orchestration; Caddy handles auth/TLS/routing, and the web UIs (Open WebUI or airpods-webui) remain responsible for their own feature surfaces.

## Role In The Stack

- Runs as a Podman-managed service (`gateway`/`caddy`) controlled by `airpods start/stop/status/logs` (with optional `start --pre-fetch` support for warming images) alongside Ollama, Open WebUI, and future web UIs.
- Default host exposure: only Open WebUI is host-facing; all other services (llama, ComfyUI, etc.) stay on the internal Podman network.
- When enabled, the gateway fronts the host entrypoint and can hide Open WebUI behind a single port:
  - Browser → `localhost:<auth_port>` → Caddy → internal Open WebUI.
- Auth posture:
  - Open WebUI remains the primary authentication surface; by default, Caddy does not add Basic Auth to Open WebUI routes.
  - Basic Auth stays optional for scenarios where an extra front-door lock is desired; otherwise Caddy is used for TLS/port consolidation.
- Remains optional: for purely local, single-user setups Caddy can be disabled and users can continue to hit Open WebUI directly.

## Capabilities (From Existing Gateway/Auth Plans)

- **Auth gateway MVP**:
  - Uses Caddy as a simple reverse proxy in front of Open WebUI.
  - Applies HTTP Basic Auth at the gateway layer with:
    - Fixed username `airpods` (for now).
    - Password read from an `auth_secret` file under `AIRPODS_HOME`.
  - Exposes a single HTTP port on the host (`auth_port`), while Open WebUI runs on an internal-only address (for example `open-webui:8080` on a Podman network).
- **Portal/auth direction**:
  - Positions Caddy as an edge proxy for both chat and portal routes when airpods-webui is introduced.
  - Handles TLS termination and authentication/authorization, while the Python backend stays largely stateless with respect to auth.
  - Supports:
    - Simple local Basic Auth for `/portal` (and optionally `/chat`) in single-user scenarios.
    - Future OIDC or external IdP integration through Caddy plugins or companion services for more advanced setups.

## Service Shapes Described So Far

- **Gateway in front of Open WebUI (MVP)**:
  - New service spec for Caddy (name typically `gateway` or `caddy`).
  - Image: `caddy:latest`.
  - Ports: host binds a single `auth_port` (for example `127.0.0.1:<auth_port>:<auth_port>`).
  - Volumes: bind or mount `AIRPODS_HOME/caddy/Caddyfile` into the container.
  - Network: attach to the same user-defined Podman network as Open WebUI and Ollama so that Caddy can reach `open-webui:8080` internally.
  - Health: simple HTTP check on `/` at the gateway port.
- **Gateway in front of airpods-webui + portal (later)**:
  - Caddy still runs as a separate service with a `ServiceSpec` similar to the MVP.
  - A Caddyfile template (stored under the Caddy config volume) routes:
    - `/chat` and `/portal` to the airpods-webui backend.
    - Optionally `/openwebui` to an Open WebUI container.
  - Basic Auth is applied at least to `/portal`, with optional protection for `/chat`.
  - TLS and host-based routing can be enabled via Caddy configuration when needed.

## Configuration Patterns (As Described)

- **AIRPODS_HOME and layout**:
  - `AIRPODS_HOME` is resolved by a helper (described in the gateway MVP plan) using:
    - `AIRPODS_HOME` env var if set.
    - `<repo-root>/config` during development.
    - A user home directory path such as `~/.airpods` for installed/production use.
  - Relevant files under `AIRPODS_HOME`:
    - `webui_secret` – existing Open WebUI secret (planned elsewhere).
    - `auth_secret` – new opaque shared secret used as the Basic Auth password.
    - `caddy/Caddyfile` – generated Caddy configuration file.
- **Secrets and helpers**:
  - Gateway plan defines helpers such as:
    - `get_auth_secret_path(home: Path) -> Path`.
    - `ensure_auth_secret(home: Path) -> str`:
      - Reads `<HOME>/auth_secret` if it exists; otherwise generates a new random secret, writes it with restrictive permissions (e.g. `0600`), and returns it.
  - Regular `airpods start` runs `ensure_auth_secret` so the gateway always has a password to use (the `--pre-fetch` path intentionally skips this because it only downloads images).
- **Auth configuration knobs**:
  - Gateway MVP plan calls for configuration fields like:
    - `auth_enabled: bool` – whether to run Caddy and hide Open WebUI behind it.
    - `auth_port: int` – the host port on which the gateway listens.
    - (Later) `auth_username: str` – defaults to `airpods` in the MVP plan.
  - Portal/auth plan further suggests configuration that controls:
    - Whether `/chat` is protected or just `/portal`.
    - Credentials when Basic Auth is used.
    - When more advanced auth (such as OIDC) is enabled.
- **Caddyfile templates**:
  - Gateway MVP plan describes a minimal Caddyfile that:
    - Listens on `:auth_port`.
    - Uses `basicauth` with username `airpods` and the `auth_secret` value as the password.
    - Reverse proxies all requests to `open-webui:8080` on the internal network.
  - Portal/auth plan describes a similar template oriented around airpods-webui:
    - Proxies `/chat` and `/portal` to a single backend.
    - Optionally proxies to Open WebUI at a separate path.
    - Enables Basic Auth for `/portal` and, optionally, `/chat`.

## How It Serves Airpods Goals

- **Single orchestrated entrypoint**:
  - Airpods remains responsible for starting containers and wiring networks and volumes; the gateway service just becomes another container in that graph.
  - With auth enabled, users access the web stack through one predictable URL and port, rather than each service exposing itself directly.
- **Safe-by-default behavior**:
  - When `auth_enabled` is true, Open WebUI is no longer bound directly to the host; Caddy is the only host-facing surface for that UI.
  - Secrets and configs live under `AIRPODS_HOME`, mirroring the production layout and keeping credentials out of the repo root.
- **Config- and template-driven design**:
  - All the moving pieces (auth flags, ports, secrets, Caddyfile contents) are derived from configuration and templated files instead of being hard-coded into commands.
  - This matches the broader design principle in `docs/goals.md` of using TOML + runtime resolution rather than ad-hoc code paths.

## Utility As A Service

- **Securing and hiding internal services**:
  - Caddy allows Open WebUI (and later airpods-webui + portal) to run on an internal network address only; the gateway controls what is reachable from the host and under what conditions.
  - For local setups, this means the web surface can be protected by a simple password, even if the machine is reachable on a LAN.
- **Providing a foundation for future auth**:
  - Because Caddy is already in front of the web surfaces, more advanced auth (hashed Basic Auth, OIDC, external IdPs) can be introduced by extending its configuration without redesigning the Python services.
  - The portal/auth plan explicitly treats Caddy as the layer responsible for TLS and authentication, letting the backend focus on service orchestration and UI.
- **Supporting different usage modes**:
  - Users who want zero extra layers can disable the gateway and access the web UIs directly.
  - Users who want a slightly more hardened local environment can enable the gateway, use Basic Auth, and route all web traffic through Caddy.
  - As airpods-webui and the portal grow, the same gateway service can front them with consistent URLs and auth behavior.

## Interaction With Service-Specific Auth

- **Open WebUI**:
  - Open WebUI maintains its own user accounts and login/session model; the gateway does not replace or manage that internal auth.
  - When the gateway is enabled in front of Open WebUI, the effective flow is “(optional) gateway Basic Auth → Open WebUI login”. By default, rely on Open WebUI login as the primary gate.
- **Services without their own auth in these plans**:
  - For services that are treated as local-only in the current plans (such as a ComfyUI deployment or the llama.cpp native WebUI), the gateway’s Basic Auth can act as the primary username/password protection in front of their HTTP endpoints.
  - This lets users benefit from a simple shared login even when a given UI does not have its own account system configured within airpods.
- **Optional and per-setup choice**:
  - Because the gateway itself is optional, users can decide whether they want an extra password gate in front of Open WebUI or rely solely on Open WebUI’s own auth.
  - Future configuration extensions can build on this pattern by allowing more granular control over which routes are protected by gateway-level auth versus service-level auth.

## Implementation Notes (From Existing Plans)

- The gateway MVP plan outlines:
  - Implementing or standardizing `get_airpods_home()` and path helpers so that `AIRPODS_HOME` resolution is consistent.
  - Adding helpers for `auth_secret` creation and retrieval.
  - Introducing a Caddy `ServiceSpec` with image, ports, volumes, network, and health URL, following the existing service pattern in `airpods/config.py`.
  - Wiring `airpods start` (while keeping `--pre-fetch` scoped to image pulls) to:
    - Ensure `auth_secret` and `Caddyfile` exist when auth is enabled.
    - Start Open WebUI without a host bind when the gateway is in use.
    - Start the gateway container and report its URL/port and auth status to the user.
  - Updating `stop`, `status`, and `logs` so the gateway appears alongside other services.
- The portal/auth plan adds:
  - A longer-term view in which Caddy fronts a unified airpods-webui backend that serves both `/chat` and `/portal`.
  - JSON APIs in airpods-webui that mirror CLI operations (using the same `ServiceManager` logic), giving the portal a GUI for starting/stopping services.
  - A roadmap for incrementally introducing Caddy (initially optional) and gradually tightening auth for `/portal` and other admin surfaces.

## Summary

- The gateway service is an optional, Caddy-based edge layer that:
  - Provides a single HTTP entrypoint in front of Open WebUI (and later airpods-webui + portal).
  - Uses `AIRPODS_HOME` to store its secrets and Caddyfile, mirroring production layouts.
  - Applies Basic Auth in the MVP using an `auth_secret` file, with room to grow into more advanced auth.
  - Is managed like any other airpods service via Podman, keeping airpods in its role as an orchestrator rather than a web server or auth provider.
- Together, the gateway/auth plans define how this service can secure, hide, and route access to the local AI stack without changing the core CLI’s responsibilities.
