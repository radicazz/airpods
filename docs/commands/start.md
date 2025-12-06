# docs/commands/start

The `airpods start` command launches AI services in Podman containers.

## Quick Start

```bash
# Start all services
airpods start

# Start specific services
airpods start ollama
airpods start open-webui

# Start with gateway enabled (see Gateway Service below)
# Edit config first: services.gateway.enabled = true
airpods start

# Initialize dependencies without starting
airpods start --init
```

## Features

The `start` command:
1. Checks Podman availability and dependencies
2. Creates networks and volumes if needed
3. Pulls container images (on first run or with `--init`)
4. Launches pods with configured services
5. Waits for health checks (HTTP endpoints)
6. Auto-configures Open WebUI admin user and imports plugins
7. Optionally starts gateway service for unified authentication (when enabled)

## Gateway Service (Optional)

The gateway service provides a unified entrypoint with authentication using Caddy as a reverse proxy.

### Enabling the Gateway

Edit your config file (`~/.config/airpods/configs/config.toml`):

```toml
[services.gateway]
enabled = true  # Change from false to true
```

### How It Works

When gateway is enabled:

1. **Single Port**: Access everything through `http://localhost:8080` (gateway)
2. **Forward Auth**: Caddy delegates authentication to Open WebUI's JWT system
3. **Internal WebUI**: Open WebUI runs on internal network only (`open-webui:8080`)
4. **Single Sign-On**: Log in once via Open WebUI, subsequent requests validated automatically

### Authentication Flow

```
Browser → Gateway (localhost:8080) 
  → Caddy checks /api/v1/users/me on Open WebUI
  → If valid JWT: proxy request to Open WebUI
  → If invalid: return 401 (user must login)
```

### Port Changes

| Service    | Gateway Disabled       | Gateway Enabled         |
|------------|------------------------|-------------------------|
| Open WebUI | `localhost:3000`       | Internal only           |
| Ollama     | `localhost:11434`      | Internal only (via `/ollama/*`) |
| Gateway    | N/A                    | `localhost:8080`        |
| ComfyUI    | `localhost:8188`       | `localhost:8188`        |

**When gateway is enabled:**
- Open WebUI accessible at `http://localhost:8080/` (requires login)
- Ollama API accessible at `http://localhost:8080/ollama/*` (requires login)
- ComfyUI remains directly accessible (will be protected in future release)

### Example Output

```
✓ Gateway started
✓ Generated Caddyfile at ~/.config/airpods/volumes/gateway/Caddyfile

Gateway running at http://localhost:8080
Open WebUI accessible via gateway only (internal: open-webui:8080)
```

### Benefits

- **Security**: Open WebUI not directly exposed to network
- **No Credential Duplication**: Uses Open WebUI's existing user database
- **Multi-User**: Supports Open WebUI's roles, permissions, OAuth, LDAP
- **Session Revocation**: Disabling user in WebUI immediately blocks access

### Disabling the Gateway

Set `enabled = false` in config and restart:

```bash
airpods stop
# Edit config: services.gateway.enabled = false
airpods start
```

Open WebUI will be accessible directly at `localhost:3000` again.

## Admin User Creation

When starting Open WebUI, airpods automatically creates a default admin account:

- **Username**: `airpods@localhost`
- **Password**: Stored in `$AIRPODS_HOME/configs/webui_admin_password`
- **Purpose**: Owns all auto-imported plugins, preventing "Deleted User" issues

### Accessing Admin Credentials

```bash
# View password location
airpods config path
# Should show: ~/.config/airpods/configs/

# Read password
cat ~/.config/airpods/configs/webui_admin_password
```

**Security Notes:**
- Password file has `0600` permissions (owner read/write only)
- Password is randomly generated using `secrets.token_urlsafe(24)`
- Password persists across restarts
- Remove with `airpods clean --configs`

## Plugin Auto-Import

When Open WebUI starts, airpods automatically:

1. **Syncs plugins** from `plugins/open-webui/` to `$AIRPODS_HOME/volumes/webui_plugins/`
2. **Creates admin user** (`airpods@localhost`) in Open WebUI's database
3. **Imports plugins** into database with proper ownership

Example output:

```
✓ Preparing Open WebUI secret
✓ Open WebUI is healthy at http://localhost:3000
✓ Airpods admin user ready (ID: abc123...)
✓ Auto-imported 6 plugin(s) into Open WebUI

Default admin credentials:
  Username: airpods@localhost
  Password: ~/.config/airpods/configs/webui_admin_password
```

All plugins are owned by "Airpods Admin" user, preventing orphaned resources.

## Options

### `--init` / `-i`
Perform initialization without starting containers:
- Checks dependencies
- Creates networks and volumes
- Pulls container images
- Creates admin user credentials

```bash
airpods start --init
```

## Health Checks

Services with HTTP endpoints are health-checked:
- **Timeout**: Configurable via `cli.startup_timeout` (default: 120 seconds)
- **Check Interval**: Configurable via `cli.startup_check_interval` (default: 5 seconds)
- Services without health checks are marked ready when pod is running

## Configuration

Customize startup behavior in `config.toml`:

```toml
[cli]
startup_timeout = 120          # Max seconds to wait for health
startup_check_interval = 5     # Seconds between health checks

[services.open-webui]
enabled = true
needs_webui_secret = true      # Auto-inject secret
```

## Examples

```bash
# Start all enabled services
airpods start

# Start only Ollama
airpods start ollama

# Initialize without starting (useful for CI/CD)
airpods start --init

# Check status after starting
airpods status
```

## Troubleshooting

**Admin user creation failed:**
- Check `airpods logs open-webui` for errors
- Ensure Open WebUI is healthy before admin user creation
- Admin user creation happens after service health check passes

**Plugins show "Auto Imported by Deleted User":**
- This should not happen with the automatic admin user
- If it occurs, restart Open WebUI: `airpods stop open-webui && airpods start open-webui`
- Check that `webui_admin_password` file exists

**Health check timeout:**
- Increase timeout in config: `cli.startup_timeout = 180`
- Check logs: `airpods logs <service>`
- Verify service is actually running: `airpods status`

## Related Commands

- `airpods stop` - Stop running services
- `airpods status` - Check service health
- `airpods logs` - View service logs
- `airpods clean` - Remove volumes/images/configs
- `airpods config` - Manage configuration

## See Also

- [Configuration Guide](config.md)
- [Plugin README](../../plugins/open-webui/README.md)
- [AGENTS.md](../../AGENTS.md)
