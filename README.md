# airpod

A rich CLI tool for easily orchestrating popular AI services locally in a portable manner with GPU-awareness.

## Features

- **Portal Mode**: Unified web portal with path-based routing (`/chat`, `/comfy`)
- **Hybrid Tunneling**: Optional Cloudflare tunnel for secure remote access
- Self-contained: all data stays in the project folder
- GPU detection with automatic passthrough to containers
- CUDA capability detection for optimal image selection
- Rich terminal output with status tables and spinners
- HTTPS reverse proxy with self-signed certificates

Easily spinup the following services:

- **Portal** – Landing page for accessing all services
- **Ollama** – Run LLMs locally (GGUF models supported)
- **Open WebUI** – Chat interface connected to Ollama
- **ComfyUI** – Node-based UI for Stable Diffusion workflows (multi-user mode)

## Requirements

- Podman (with podman-compose)
- Python 3.10+
- NVIDIA GPU drivers (optional, but recommended for ComfyUI)
- OpenSSL (for generating self-signed certificates)

## Install

```bash
# Create venv and install
uv venv && uv pip install -e .

# Activate to use airpod command
source .venv/bin/activate
```

## Usage

```bash
airpod init       # Verify environment, create dirs, pull images
airpod start      # Start all services (alias: up)
airpod status     # Show service status (alias: ps)
airpod logs       # View logs
airpod stop       # Stop services (alias: down)
airpod path       # Show data storage locations
```

Run `airpod --help` for all options.

### Starting Specific Services

```bash
airpod start ollama open-webui    # Start only Ollama and Open WebUI
airpod start comfyui              # Start only ComfyUI
airpod start --cpu                # Force CPU mode (disable GPU)
```

### Accessing Services

#### Portal Mode (Default)

After running `airpod start`, all services are accessible via a unified portal:

- **Portal**: https://localhost:8443/ (landing page with service cards)
- **Open WebUI**: https://localhost:8443/chat (AI chat interface)
- **ComfyUI**: https://localhost:8443/comfy (Stable Diffusion workflows)
- **Ollama**: Internal only (accessed via Open WebUI)

#### Legacy Mode

Run with `--no-portal` for port-based access:

```bash
airpod start --no-portal
```

- **Open WebUI**: https://localhost:8443
- **ComfyUI**: https://localhost:8444

Note: You'll need to accept the self-signed certificate warning in your browser.

### Remote Access (Cloudflare Tunnel)

Airpod supports **two types of Cloudflare tunnels** for secure remote access:

#### 🚀 Quick Tunnel (Temporary URL) - Easiest!

**Perfect for:** Testing, demos, temporary sharing - **NO LOGIN REQUIRED!**

```bash
# 1. Start your services
airpod start --portal

# 2. Start quick tunnel (gets a free .trycloudflare.com URL)
airpod tunnel quick

# You'll get a temporary URL like: https://random-words-123.trycloudflare.com
# Share this URL to access your services remotely!

# 3. Stop when done
airpod tunnel quick --stop
```

**Features:**
- ✅ No Cloudflare account needed
- ✅ No DNS setup required  
- ✅ URL ready in ~15 seconds
- ⚠️ Temporary - expires when stopped
- ⚠️ Random URL each time

#### 🏗️ Permanent Tunnel (Custom Domain)

**Perfect for:** Production, permanent access, custom branding

```bash
# 1. Install cloudflared (one-time setup)
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o cloudflared.deb
sudo dpkg -i cloudflared.deb

# 2. Login to Cloudflare
cloudflared tunnel login

# 3. Create tunnel
airpod tunnel init --hostname airpod.yourdomain.com

# 4. Configure DNS (follow on-screen instructions)

# 5. Start services with tunnel enabled
airpod start --tunnel
```

`airpod start --tunnel` automatically enables the HTTPS portal and Caddy gateway (path-based routing) so that `/chat` and `/comfy` are reachable remotely through `https://<your-hostname>`. The command will refuse to run together with `--no-portal`, because the tunnel depends on the unified portal routing.

Airpod keeps the Cloudflare credential JSON inside `./volumes/cloudflared/` and renders `config/cloudflared.yml` from `config/cloudflared.yml.template`, keeping the entire tunnel setup self-contained.

**Hybrid Mode**: Services remain accessible locally (`https://localhost:8443`) while also being available remotely through your Cloudflare tunnel URL. You can enable/disable the tunnel at any time without affecting local access. `airpod status` now reports tunnel health so you can see at a glance whether it is connected.

**Tunnel Commands**:
- `airpod tunnel quick` - Start temporary tunnel (no auth needed!)
- `airpod tunnel quick --stop` - Stop temporary tunnel
- `airpod tunnel init` - Create a permanent tunnel
- `airpod tunnel status` - Show tunnel status
- `airpod tunnel delete` - Remove permanent tunnel

See [TUNNEL_QUICKSTART.md](./TUNNEL_QUICKSTART.md) for detailed instructions.

## GPU Compatibility

Airpod automatically detects your GPU and CUDA compute capability to select the optimal Docker images:

- **CUDA ≥ 7.0** (e.g., RTX 20/30/40 series): Uses latest CUDA-enabled images
- **CUDA < 7.0** (e.g., GTX 1070, compute 6.1): Uses CPU-compatible images
- **No GPU**: Falls back to CPU-only images

ComfyUI runs in multi-user mode, allowing multiple users to work with isolated workflows when authenticated through Open WebUI.

## Data Storage

All service data is stored locally in `./volumes/`:

- `data-ollama/` – Ollama models and configuration
- `data-open-webui/` – Open WebUI database and uploads
- `data-comfyui/` – ComfyUI models, outputs, and workflows
- `shared/` – Shared storage for future services

To backup everything, simply copy the entire project folder.

## Troubleshooting

### ComfyUI won't start on older GPU

If you have a GPU with CUDA compute capability < 7.0 (like GTX 1070), airpod will automatically use a CPU-compatible image. Check your GPU capability:

```bash
nvidia-smi --query-gpu=compute_cap --format=csv,noheader
```

### Certificate warnings

The self-signed certificate will trigger browser warnings. This is expected for local development. Click "Advanced" and proceed to the site.

### Ports already in use

If ports 8443/8444 are already in use, stop the conflicting services or modify the port mappings in `airpod/config.py`.

## License

See [LICENSE](./LICENSE).
