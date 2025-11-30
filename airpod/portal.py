"""Portal configuration and management."""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Literal, List

import bcrypt


@dataclass
class PortalConfig:
    """Portal service configuration."""
    title: str = "Airpod Services"
    enable_auth: bool = False
    auth_username: Optional[str] = None
    auth_password_hash: Optional[str] = None  # bcrypt hash
    theme: Literal["light", "dark", "auto"] = "dark"


@dataclass
class ServiceRoute:
    """Service routing configuration for portal."""
    name: str
    display_name: str
    path: str  # e.g., "/chat", "/comfy"
    internal_url: str  # e.g., "http://host.containers.internal:3000"
    icon: str  # emoji or icon identifier
    description: str
    requires_auth: bool = True
    enabled: bool = True


def get_portal_config_path() -> Path:
    """Get path to portal configuration file."""
    from airpod.config import CONFIG_DIR
    return CONFIG_DIR / "portal.json"


def load_portal_config() -> PortalConfig:
    """Load portal configuration from config/portal.json."""
    config_path = get_portal_config_path()
    if not config_path.exists():
        # Return default config
        return PortalConfig()
    
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return PortalConfig(**data)
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError(f"Failed to load portal config: {exc}") from exc


def save_portal_config(config: PortalConfig) -> None:
    """Save portal configuration to config/portal.json."""
    config_path = get_portal_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    data = asdict(config)
    config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def hash_password(password: str) -> str:
    """Hash password with bcrypt."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    except Exception:
        return False


def get_service_routes() -> List[ServiceRoute]:
    """Get list of configured service routes."""
    return [
        ServiceRoute(
            name="open-webui",
            display_name="Chat",
            path="/chat",
            internal_url="http://host.containers.internal:3000",
            icon="💬",
            description="AI Chat Interface",
            requires_auth=True,
            enabled=True,
        ),
        ServiceRoute(
            name="comfyui",
            display_name="ComfyUI",
            path="/comfy",
            internal_url="http://host.containers.internal:8188",
            icon="🎨",
            description="Stable Diffusion Workflows",
            requires_auth=True,
            enabled=True,
        ),
    ]


def update_service_route(name: str, **kwargs) -> None:
    """Update a service route configuration."""
    # For now, service routes are hardcoded
    # This can be extended to store custom route configs
    pass
