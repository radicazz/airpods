# docs/plans/service-gateway

Status: proposed; no gateway service, auth settings, or gateway-secret helpers are implemented.

## Purpose

Explore an optional Caddy container that supplies TLS and a single entrypoint for existing service interfaces. Airpods would orchestrate it through the same runtime abstraction as other services; Caddy would handle routing and optional additional authentication. Open WebUI would retain its own accounts and login.

## Decisions Required Before Implementation

- Define routing and health checks for the existing services without adding a custom web portal.
- Resolve backend exposure: current services use host networking and may listen on all interfaces. Adding a proxy alone cannot hide those listeners. Any isolation or loopback-bind design must work with both Podman and Docker.
- Design opt-in configuration, credentials, and Caddyfile generation under the existing state root, with secrets in `configs/`. Do not introduce another home-directory convention.
- Define authentication defaults and password hashing, preserving WebUI's authentication.

## Proposed Delivery

Add schema/defaults, secret/config preparation, a service spec, and lifecycle reporting only after those decisions are settled. Keep `--pre-fetch` limited to image preparation. Verify direct backend exposure, authentication, restart/reuse, and both runtimes before documenting the gateway as supported.
