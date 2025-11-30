"""Cloudflare tunnel management for remote access."""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from airpod.config import CLOUDFLARED_CONFIG, CLOUDFLARED_TEMPLATE, CLOUDFLARED_VOLUME


@dataclass
class TunnelConfig:
    """Cloudflare tunnel configuration."""
    tunnel_id: Optional[str] = None  # UUID from cloudflared tunnel create
    tunnel_name: str = "airpod-tunnel"
    account_id: Optional[str] = None  # Cloudflare account ID
    tunnel_token: Optional[str] = None  # Tunnel credentials token
    hostname: Optional[str] = None  # e.g., airpod.yourdomain.com
    enabled: bool = False  # Whether tunnel is currently active


def get_tunnel_config_path() -> Path:
    """Get path to tunnel configuration file."""
    from airpod.config import CONFIG_DIR
    return CONFIG_DIR / "tunnel.json"


def load_tunnel_config() -> TunnelConfig:
    """Load tunnel configuration from config/tunnel.json."""
    config_path = get_tunnel_config_path()
    if not config_path.exists():
        # Return default config
        return TunnelConfig()
    
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return TunnelConfig(**data)
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError(f"Failed to load tunnel config: {exc}") from exc


def save_tunnel_config(config: TunnelConfig) -> None:
    """Save tunnel configuration to config/tunnel.json."""
    config_path = get_tunnel_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    data = asdict(config)
    config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _credentials_source_path(tunnel_id: str) -> Path:
    return Path.home() / ".cloudflared" / f"{tunnel_id}.json"


def _credentials_target_path(tunnel_id: str) -> Path:
    return CLOUDFLARED_VOLUME / f"{tunnel_id}.json"


def ensure_cloudflared_credentials(config: Optional[TunnelConfig] = None) -> Path:
    """Ensure tunnel credentials are stored within the project tree."""
    cfg = config or load_tunnel_config()
    if not cfg.tunnel_id:
        raise RuntimeError("no tunnel configured. run 'airpod tunnel init' first")
    target = _credentials_target_path(cfg.tunnel_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return target
    source = _credentials_source_path(cfg.tunnel_id)
    if not source.exists():
        raise RuntimeError(
            "Cloudflare credentials not found. Run 'cloudflared tunnel create' or copy the credential JSON into volumes/cloudflared/."
        )
    shutil.copy2(source, target)
    return target


def remove_cloudflared_credentials(tunnel_id: str) -> None:
    """Remove stored credentials for the given tunnel id."""
    target = _credentials_target_path(tunnel_id)
    if target.exists():
        target.unlink()


def ensure_cloudflared_config(config: Optional[TunnelConfig] = None) -> Path:
    """Render cloudflared.yml from template and return its path."""
    cfg = config or load_tunnel_config()
    if not cfg.tunnel_id:
        raise RuntimeError("no tunnel configured. run 'airpod tunnel init' first")
    if not CLOUDFLARED_TEMPLATE.exists():
        raise RuntimeError(f"cloudflared template missing at {CLOUDFLARED_TEMPLATE}")
    ingress_rule = (
        f"  - hostname: {cfg.hostname}\n    service: https://host.containers.internal:8443"
        if cfg.hostname
        else "  - service: https://host.containers.internal:8443"
    )
    ingress_block = ingress_rule + "\n"
    content = CLOUDFLARED_TEMPLATE.read_text(encoding="utf-8").format(
        TUNNEL_ID=cfg.tunnel_id,
        INGRESS_RULES=ingress_block,
    )
    CLOUDFLARED_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CLOUDFLARED_CONFIG.write_text(content, encoding="utf-8")
    return CLOUDFLARED_CONFIG


def check_cloudflared_installed() -> tuple[bool, str]:
    """Check if cloudflared is installed."""
    try:
        result = subprocess.run(
            ["cloudflared", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            return True, version
        return False, "cloudflared returned non-zero exit code"
    except FileNotFoundError:
        return False, "cloudflared not found"
    except Exception as exc:
        return False, str(exc)


def create_tunnel(tunnel_name: str) -> TunnelConfig:
    """Create a new Cloudflare tunnel using cloudflared.
    
    Note: This requires cloudflared to be installed and logged in.
    Run: cloudflared tunnel login
    """
    try:
        # Create the tunnel
        result = subprocess.run(
            ["cloudflared", "tunnel", "create", tunnel_name],
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Failed to create tunnel: {result.stderr}")
        
        # Parse output to get tunnel ID
        # Output format: "Created tunnel <name> with id <uuid>"
        output = result.stdout
        tunnel_id = None
        for line in output.split("\n"):
            if "with id" in line:
                parts = line.split("with id")
                if len(parts) > 1:
                    tunnel_id = parts[1].strip()
                    break
        
        if not tunnel_id:
            raise RuntimeError(f"Could not parse tunnel ID from output: {output}")
        
        config = TunnelConfig(
            tunnel_id=tunnel_id,
            tunnel_name=tunnel_name,
        )
        save_tunnel_config(config)
        ensure_cloudflared_credentials(config)
        return config
        
    except subprocess.TimeoutExpired:
        raise RuntimeError("Tunnel creation timed out")
    except Exception as exc:
        raise RuntimeError(f"Failed to create tunnel: {exc}") from exc


def delete_tunnel(tunnel_name: str) -> None:
    """Delete a Cloudflare tunnel."""
    config = load_tunnel_config()
    try:
        result = subprocess.run(
            ["cloudflared", "tunnel", "delete", tunnel_name],
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Failed to delete tunnel: {result.stderr}")
        
        if config.tunnel_id:
            remove_cloudflared_credentials(config.tunnel_id)
        # Remove config file
        config_path = get_tunnel_config_path()
        if config_path.exists():
            config_path.unlink()
            
    except Exception as exc:
        raise RuntimeError(f"Failed to delete tunnel: {exc}") from exc


def get_temp_tunnel_url() -> Optional[str]:
    """Extract the temporary URL from cloudflared container logs."""
    try:
        result = subprocess.run(
            ["podman", "logs", "airpod-cloudflared-quick-0"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        
        if result.returncode == 0:
            # Look for the trycloudflare.com URL in logs
            for line in result.stdout.split("\n"):
                if "trycloudflare.com" in line and "https://" in line:
                    # Extract URL from log line
                    import re
                    match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', line)
                    if match:
                        return match.group(0)
        return None
    except Exception:
        return None


def get_tunnel_status() -> dict:
    """Get current tunnel status.
    
    Returns dict with: running (bool), url (str), uptime (str)
    """
    config = load_tunnel_config()
    
    # Check for quick tunnel first
    try:
        from airpod import podman
        quick_running = podman.container_exists("airpod-cloudflared-quick-0")
        if quick_running:
            temp_url = get_temp_tunnel_url()
            return {
                "running": True,
                "url": temp_url,
                "configured": True,
                "tunnel_name": "quick-tunnel",
                "type": "quick",
            }
    except:
        pass
    
    if not config.tunnel_id:
        return {
            "running": False,
            "url": None,
            "configured": False,
        }
    
    # Check if cloudflared process is running
    # This is a simple check - in production you'd check podman containers
    try:
        from airpod import podman
        running = podman.container_exists("airpod-cloudflared-0")
    except:
        running = False
    
    return {
        "running": running,
        "url": config.hostname,
        "configured": True,
        "tunnel_name": config.tunnel_name,
        "type": "permanent",
    }


def validate_tunnel_config() -> tuple[bool, str]:
    """Validate tunnel configuration."""
    config = load_tunnel_config()
    
    if not config.tunnel_id:
        return False, "No tunnel configured. Run 'airpod tunnel init' first."
    if not config.hostname:
        return False, "Tunnel hostname missing. Re-run 'airpod tunnel init --hostname <domain>' or edit config/tunnel.json."
    
    # Check if cloudflared is installed
    installed, msg = check_cloudflared_installed()
    if not installed:
        return False, f"cloudflared not installed: {msg}"
    if not CLOUDFLARED_TEMPLATE.exists():
        return False, f"Template missing at {CLOUDFLARED_TEMPLATE}"
    target = _credentials_target_path(config.tunnel_id)
    source = _credentials_source_path(config.tunnel_id)
    if not target.exists() and not source.exists():
        return False, (
            "Tunnel credentials missing. Copy the JSON from ~/.cloudflared/ into volumes/cloudflared/ or re-run 'airpod tunnel init'."
        )
    
    return True, "Tunnel configuration valid"