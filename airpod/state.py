from __future__ import annotations

import secrets
from pathlib import Path


def config_dir() -> Path:
    """Return the local project config directory (self-contained)."""
    from airpod.config import CONFIG_DIR
    return CONFIG_DIR


def ensure_config_dir() -> Path:
    path = config_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_webui_secret() -> str:
    """Return a persistent secret for Open WebUI sessions."""
    cfg = ensure_config_dir()
    secret_file = cfg / "webui_secret"
    if secret_file.exists():
        return secret_file.read_text(encoding="utf-8").strip()
    secret = secrets.token_urlsafe(32)
    secret_file.write_text(secret, encoding="utf-8")
    return secret
