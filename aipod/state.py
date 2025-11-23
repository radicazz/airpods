from __future__ import annotations

import os
import secrets
from pathlib import Path


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "aipod"
    return Path.home() / ".config" / "aipod"


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
