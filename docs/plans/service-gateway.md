# docs/plans/service-gateway

**STATUS:** ✅ IMPLEMENTED (MVP Complete)

## Purpose

- Add an optional Caddy-based gateway service that sits in front of existing web UIs (initially Open WebUI, later airpods-webui + portal) to provide a single HTTP entrypoint with unified authentication.
- Use the same `AIRPODS_HOME`-driven layout and Podman orchestration that airpods uses for other services, so the gateway is configured and managed like the rest of the stack.
- Keep airpods focused on orchestration; Caddy handles auth/TLS/routing via forward authentication to Open WebUI's JWT system, while the web UIs remain responsible for their own feature surfaces.

## Role In The Stack

- Runs as a Podman-managed service (`gateway`/`caddy`) controlled by `airpods init/start/stop/status/logs` alongside Ollama, Open WebUI, and future web UIs.
- Default host exposure: only Open WebUI is host-facing; all other services (Ollama, ComfyUI, etc.) stay on the internal Podman network.
- When enabled, the gateway fronts the host entrypoint and hides Open WebUI behind a single port:
  - Browser → `localhost:<gateway_port>` → Caddy (auth check) → internal Open WebUI.
- Auth posture:
  - **Forward Auth to Open WebUI**: Caddy delegates authentication to Open WebUI's existing JWT/session system via `forward_auth` directive.
  - **Single Sign-On Experience**: Users log in once via Open WebUI's native login (proxied through Caddy); all subsequent requests are validated by Caddy calling Open WebUI's `/api/v1/users/me` endpoint.
  - **No credential duplication**: Leverages Open WebUI's user database, password hashing (bcrypt), and session management without reimplementing auth logic.
  - **Optional Basic Auth layer**: For additional security, Basic Auth can be layered on top for `/portal` admin routes while chat routes use Open WebUI auth only.
- Remains optional: for purely local, single-user setups Caddy can be disabled and users can continue to hit Open WebUI directly.

## Capabilities

### Phase 1: Forward Auth MVP (Open WebUI Integration)
- **Unified authentication**:
  - Caddy uses `forward_auth` to delegate authentication to Open WebUI's JWT/session verification.
  - Every protected request triggers Caddy to call `http://open-webui:8080/api/v1/users/me` with forwarded `Cookie` and `Authorization` headers.
  - Open WebUI validates JWT signature (using `WEBUI_SECRET_KEY`), checks expiration, and verifies user exists in database.
  - If valid (HTTP 200), Caddy proxies request; if invalid (401/403), Caddy blocks access.
- **Login flow**:
  - `/api/v1/auths/*` and `/auth/*` routes bypass forward auth to allow login form access.
  - Users authenticate via Open WebUI's native login (username/password, OAuth, LDAP).
  - Open WebUI issues JWT token (via `Authorization: Bearer` header or HTTP-only cookie).
  - Caddy caches auth context for duration of session.
- **Security benefits**:
  - Single HTTP port exposed to host (`gateway_port`, e.g., 8080).
  - Open WebUI port (3000) bound only to internal Podman network (`open-webui:8080`).
  - All authentication logic remains in Open WebUI (no credential sync, no password files).
  - Leverages existing Open WebUI features: password hashing (bcrypt), session management, user roles.

### Phase 2: Portal/Admin Protection (Future)
- **Two-tier auth model**:
  - `/chat` routes: Forward auth to Open WebUI (regular user login).
  - `/portal` routes: Optional Basic Auth layer for admin access (using `auth_secret` from `AIRPODS_HOME/configs/`).
- **Airpods-webui integration**:
  - Positions Caddy as edge proxy for unified airpods-webui backend serving both chat and portal.
  - Handles TLS termination and route-specific authentication policies.
- **Advanced auth options** (stretch goals):
  - OIDC/OAuth integration via Caddy plugins (e.g., `caddy-security`).
  - External IdP support for enterprise deployments.
  - JWT validation directly in Caddy using `caddy-jwt` plugin (requires secret sync with Open WebUI).

## Service Architecture

### Phase 1: Gateway Service Spec (Open WebUI Forward Auth)
```toml
[services.gateway]
enabled = false  # Opt-in feature
image = "docker.io/caddy:2.8-alpine"
pod = "gateway"
container = "caddy-0"
network_aliases = ["gateway", "caddy"]
ports = [
  { host = 8080, container = 80 }
]
volumes = {
  config = {
    source = "bind://gateway/Caddyfile",
    target = "/etc/caddy/Caddyfile",
    readonly = true
  },
  data = {
    source = "bind://gateway/data",
    target = "/data"
  }
}
health = { path = "/", expected_status = [200, 399] }
env = {}
needs_webui_secret = false  # Auth delegated to Open WebUI
```

**Caddyfile Template** (`$AIRPODS_HOME/volumes/gateway/Caddyfile`):
```caddyfile
{
  # Global options
  auto_https off
  admin off
}

:80 {
  # Allow Open WebUI login routes (bypass forward auth)
  @login {
    path /api/v1/auths/* /auth/*
  }
  handle @login {
    reverse_proxy open-webui:8080
  }
  
  # Forward auth for all other routes
  @protected {
    not path /api/v1/auths/* /auth/*
  }
  handle @protected {
    forward_auth open-webui:8080 {
      uri /api/v1/users/me
      copy_headers Cookie Authorization
    }
    reverse_proxy open-webui:8080
  }
}
```

### Phase 2: Unified Backend with Portal (Future)
```caddyfile
:80 {
  # Login routes (no auth)
  handle /api/v1/auths/* {
    reverse_proxy open-webui:8080
  }
  
  # Admin portal (optional Basic Auth + forward auth)
  handle /portal/* {
    basicauth {
      airpods {env.AUTH_SECRET_HASH}
    }
    forward_auth open-webui:8080 {
      uri /api/v1/users/me
      copy_headers Cookie Authorization
    }
    reverse_proxy airpods-webui:8000
  }
  
  # Chat routes (forward auth only)
  handle /* {
    forward_auth open-webui:8080 {
      uri /api/v1/users/me
      copy_headers Cookie Authorization
    }
    reverse_proxy open-webui:8080
  }
}
```

**Port Binding Changes When Gateway Enabled**:
- Open WebUI: Remove host bind, only expose on `airpods_network` (internal `open-webui:8080`).
- Gateway: Bind `localhost:8080:80` (or user-configured `gateway_port`).
- ComfyUI/other services: Remain internal-only unless explicitly exposed.

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
  - `airpods init` and `airpods start` are expected to call `ensure_auth_secret` so the gateway always has a password to use.
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
  - Airpods remains responsible for starting containers and wiring networks and volumes; the gateway service becomes another managed container in the dependency graph.
  - With gateway enabled, users access the web stack through one predictable URL (`http://localhost:8080`) instead of service-specific ports.
- **Safe-by-default behavior**:
  - When `gateway.enabled = true`, Open WebUI is no longer bound directly to the host; Caddy is the only host-facing surface for web UIs.
  - Authentication remains centralized in Open WebUI's database (no credential duplication, no plaintext password files).
  - Secrets and configs live under `AIRPODS_HOME/configs` and `AIRPODS_HOME/volumes`, keeping runtime assets grouped together.
- **Config- and template-driven design**:
  - Gateway service spec follows same pattern as Ollama/Open WebUI/ComfyUI (TOML config with template variables).
  - Caddyfile generated dynamically during `airpods start` using existing template resolver (`{{services.*.ports.*}}`).
  - Port binding logic conditional on `gateway.enabled` flag (no hard-coded paths).
- **Zero Open WebUI code changes**:
  - Leverages Open WebUI's existing `/api/v1/users/me` endpoint for session validation.
  - No custom auth middleware, no API keys, no credential sync.
  - Works with Open WebUI's built-in authentication methods (password, OAuth, LDAP).

## Utility As A Service

- **Securing and hiding internal services**:
  - Caddy allows Open WebUI (and later airpods-webui + portal) to run on an internal network address only (`open-webui:8080` on `airpods_network`).
  - Gateway controls what is reachable from the host and enforces authentication before proxying requests.
  - For local setups accessible on a LAN, gateway provides centralized access control without modifying service containers.
- **Single sign-on across services**:
  - Users log in once via Open WebUI's login form (username/password).
  - JWT token issued by Open WebUI is validated by Caddy for all subsequent requests.
  - Future services (airpods-webui portal, ComfyUI with auth, etc.) can leverage same session via forward auth.
- **Foundation for advanced auth**:
  - Forward auth pattern supports evolution:
    - **Phase 1**: JWT validation via Open WebUI API call.
    - **Phase 2**: Optional Basic Auth layer for admin routes (`/portal`).
    - **Phase 3**: OIDC/OAuth integration via Caddy plugins (enterprise scenarios).
  - Caddy config can be extended without modifying Python backend or service containers.
  - TLS termination and certificate management handled by Caddy (Let's Encrypt, self-signed, etc.).
- **Supporting different usage modes**:
  - **Disabled gateway** (default): Direct access to Open WebUI at `localhost:3000`, ComfyUI at `localhost:8188`, etc. (current behavior).
  - **Enabled gateway**: Single entrypoint at `localhost:8080` with unified auth; internal services unreachable from host.
  - **Partial gateway**: Gateway fronts Open WebUI only; other services remain directly accessible (mixed mode).

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

## Implementation Roadmap (Commit-Oriented)

### Commit 1: `feat: add gateway service to configuration schema`
**Files**:
- `airpods/configuration/defaults.py`
- `airpods/configuration/schema.py`

**Changes**:
```python
# defaults.py - Add gateway service to DEFAULT_CONFIG_DICT
"gateway": {
    "enabled": False,  # Opt-in feature
    "image": "docker.io/caddy:2.8-alpine",
    "pod": "gateway",
    "container": "caddy-0",
    "network_aliases": ["gateway", "caddy"],
    "ports": [{"host": 8080, "container": 80}],
    "volumes": {
        "config": {
            "source": "bind://gateway/Caddyfile",
            "target": "/etc/caddy/Caddyfile",
            "readonly": True,
        },
        "data": {"source": "bind://gateway/data", "target": "/data"},
    },
    "health": {"path": "/", "expected_status": [200, 399]},
    "env": {},
    "needs_webui_secret": False,
}
```

**Testing**: `uv run pytest tests/configuration/` passes with new service schema.

---

### Commit 2: `feat: add gateway state helpers for Caddyfile management`
**Files**:
- `airpods/state.py`
- `tests/test_state.py`

**Changes**:
```python
# state.py
def gateway_caddyfile_path() -> Path:
    """Return path to generated Caddyfile."""
    return volumes_dir() / "gateway" / "Caddyfile"

def ensure_gateway_caddyfile(content: str) -> Path:
    """Write Caddyfile content to gateway volume directory."""
    path = gateway_caddyfile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
```

**Tests**: Add unit tests for path resolution and file creation.

---

### Commit 3: `feat: add Caddyfile template with forward auth`
**Files**:
- `configs/gateway/Caddyfile.template` (new)
- `airpods/configuration/resolver.py` (template loading logic)

**Changes**:
```caddyfile
# configs/gateway/Caddyfile.template
{
  auto_https off
  admin off
}

:{{services.gateway.ports.0.container}} {
  # Allow Open WebUI login routes (bypass forward auth)
  @login path /api/v1/auths/* /auth/*
  handle @login {
    reverse_proxy open-webui:{{services.open-webui.ports.0.container}}
  }
  
  # Forward auth for all other routes
  @protected not path /api/v1/auths/* /auth/*
  handle @protected {
    forward_auth open-webui:{{services.open-webui.ports.0.container}} {
      uri /api/v1/users/me
      copy_headers Cookie Authorization
    }
    reverse_proxy open-webui:{{services.open-webui.ports.0.container}}
  }
}
```

**Testing**: Template resolver can parse and substitute variables correctly.

---

### Commit 4: `feat: implement dynamic port binding for gateway-enabled mode`
**Files**:
- `airpods/services.py`
- `airpods/configuration/loader.py`

**Changes**:
```python
# services.py - Add logic to modify service specs based on gateway.enabled
def resolve_service_specs(config: RuntimeConfig) -> list[ServiceSpec]:
    """Resolve service specs with dynamic port binding."""
    specs = []
    gateway_enabled = config.services.get("gateway", {}).get("enabled", False)
    
    for name, svc_config in config.services.items():
        if not svc_config.enabled:
            continue
        
        spec = ServiceSpec.from_config(name, svc_config)
        
        # If gateway is enabled, remove Open WebUI host port binding
        if gateway_enabled and name == "open-webui":
            spec.ports = []  # Internal-only on airpods_network
        
        specs.append(spec)
    
    return specs
```

**Testing**: Unit test verifies Open WebUI ports removed when `gateway.enabled = True`.

---

### Commit 5: `feat: integrate gateway into start command`
**Files**:
- `airpods/cli/commands/start.py`

**Changes**:
```python
# After Open WebUI health check passes in start command
if gateway_spec := [s for s in specs if s.name == "gateway"]:
    with status_spinner("Generating Caddyfile from template"):
        template_path = detect_repo_root() / "configs/gateway/Caddyfile.template"
        template_content = template_path.read_text(encoding="utf-8")
        from airpods.configuration.resolver import TemplateResolver
        resolver = TemplateResolver(manager.runtime.get_config())
        resolved_content = resolver.resolve(template_content)
        state.ensure_gateway_caddyfile(resolved_content)
    
    with status_spinner("Starting gateway service"):
        manager.start_service(gateway_spec[0], gpu_available=False, force_cpu=True)
    
    # Update service URLs to point to gateway
    console.print("[ok]Gateway started at http://localhost:8080[/]")
    console.print("[info]Open WebUI accessible via gateway only (internal: open-webui:8080)[/]")
```

**Testing**: Manual test with `gateway.enabled = True` in config.toml.

---

### Commit 6: `feat: add gateway to status/logs/stop commands`
**Files**:
- `airpods/cli/commands/status.py`
- `airpods/cli/commands/logs.py`
- `airpods/cli/commands/stop.py`

**Changes**:
- `status`: Gateway appears in service table with health check
- `logs`: `airpods logs gateway` tails Caddy container logs
- `stop`: `airpods stop` includes gateway in shutdown sequence

**Testing**: Verify gateway shows in `airpods status` output when enabled.

---

### Commit 7: `test: add integration tests for gateway forward auth`
**Files**:
- `tests/integration/test_gateway.py` (new)

**Changes**:
```python
# tests/integration/test_gateway.py
def test_gateway_forward_auth():
    """Test gateway delegates auth to Open WebUI."""
    # Start services with gateway enabled
    # Attempt unauthenticated request → expect 401
    # Login via /api/v1/auths/signin → get JWT
    # Authenticated request with JWT → expect 200
    # Verify Caddy called /api/v1/users/me
```

**Testing**: Integration tests pass (requires Podman).

---

### Commit 8: `docs: add gateway service usage documentation`
**Files**:
- `docs/commands/start.md`
- `README.md`

**Changes**:
- Document `services.gateway.enabled` configuration option
- Explain forward auth vs direct access
- Add example: enabling gateway in `config.toml`
- Update port table (8080 for gateway, 3000 becomes internal-only)

---

### Future Work (Post-MVP)

#### Commit 9+: Portal admin routes with Basic Auth
- Add `auth_secret` helpers to `state.py`
- Extend Caddyfile template with `/portal` routes
- Add `airpods-webui` backend service

#### Commit 10+: Advanced features
- TLS certificate management
- OIDC/OAuth plugin integration
- Multi-service routing (ComfyUI, custom backends)
- Rate limiting and access logs

## Summary

The gateway service is an **optional, Caddy-based reverse proxy** that provides unified authentication and secure access control for the airpods AI stack:

**Key Features**:
- **Forward Authentication**: Delegates session validation to Open WebUI's JWT system via `/api/v1/users/me` endpoint
- **Single Sign-On**: Users log in once via Open WebUI; Caddy validates subsequent requests without credential duplication
- **Zero Code Changes**: Leverages Open WebUI's existing auth (bcrypt passwords, JWT tokens, user database)
- **Network Isolation**: Hides internal services (Open WebUI, ComfyUI) behind gateway; only gateway port exposed to host
- **Config-Driven**: Enabled via `services.gateway.enabled = true`; Caddyfile generated from templates using existing resolver
- **Optional**: Default disabled; users can choose direct access or gateway-fronted access

**Implementation Strategy**:
- **8 focused commits** for MVP (configuration → state helpers → template → dynamic ports → start integration → CLI commands → tests → docs)
- Each commit is independently testable and reviewable
- Follows existing airpods patterns (TOML config, template resolution, Podman orchestration)
- CI/CD compatible (tests run in isolation, no Podman required for unit tests)

**Benefits Over Basic Auth Approach**:
- No plaintext password files (auth delegated to Open WebUI)
- Supports Open WebUI's multi-user system (roles, permissions, OAuth, LDAP)
- User management via Open WebUI Admin Panel (no CLI password resets)
- Session revocation works immediately (disable user → forward auth returns 401)
- Compatible with Open WebUI's future auth enhancements (SSO, MFA, etc.)

**Development Timeline** (estimated):
- Commits 1-3: Configuration & templates (~2-3 hours)
- Commits 4-6: Integration with CLI commands (~3-4 hours)
- Commits 7-8: Testing & documentation (~2-3 hours)
- **Total MVP**: ~8-10 hours of focused development

This plan enables secure, production-ready deployments while keeping airpods focused on orchestration rather than reimplementing authentication.
