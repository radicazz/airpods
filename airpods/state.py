from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Optional, Union

from airpods.paths import detect_repo_root

STATE_ROOT_ENV = "AIRPODS_HOME"
_STATE_ROOT_OVERRIDE: Optional[Path] = None


def _detect_repo_root() -> Optional[Path]:
    """Backwards-compatible wrapper that delegates to airpods.paths."""
    return detect_repo_root(Path(__file__).resolve())


@lru_cache(maxsize=1)
def state_root() -> Path:
    if _STATE_ROOT_OVERRIDE is not None:
        return _STATE_ROOT_OVERRIDE
    env = os.environ.get(STATE_ROOT_ENV)
    if env:
        return Path(env).expanduser().resolve()
    xdg_base = os.environ.get("XDG_CONFIG_HOME")
    repo_root = _detect_repo_root()
    if repo_root and os.access(repo_root, os.W_OK) and not xdg_base:
        return repo_root
    if xdg_base:
        return Path(xdg_base).expanduser() / "airpods"
    return Path.home() / ".config" / "airpods"


def set_state_root(path: Union[str, os.PathLike[str]]) -> None:
    """Force the state root (configs/volumes/etc.) to live under ``path``."""

    global _STATE_ROOT_OVERRIDE
    _STATE_ROOT_OVERRIDE = Path(path).expanduser().resolve()
    state_root.cache_clear()


def clear_state_root_override() -> None:
    """Reset any previously forced state root path."""

    global _STATE_ROOT_OVERRIDE
    _STATE_ROOT_OVERRIDE = None
    state_root.cache_clear()


def configs_dir() -> Path:
    path = state_root() / "configs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_dir() -> Path:
    return configs_dir()


def ensure_config_dir() -> Path:
    return configs_dir()


def volumes_dir() -> Path:
    path = state_root() / "volumes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_volume_path(relative: Union[str, os.PathLike[str]]) -> Path:
    path = Path(relative)
    if not str(path).strip():
        raise ValueError("volume path cannot be empty")
    if path.is_absolute():
        return path
    base = volumes_dir().resolve()
    resolved = (base / path).resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError("volume path must stay within the volumes directory") from exc
    return resolved


def _normalize_source(path: Union[str, os.PathLike[str]]) -> Path:
    return Path(path).expanduser()


def ensure_volume_source(source: Union[str, os.PathLike[str]]) -> tuple[Path, bool]:
    path = _normalize_source(source)
    existed = path.exists()
    if path.is_absolute():
        path.mkdir(parents=True, exist_ok=True)
    created = path.is_absolute() and not existed
    return path, created


def webui_secret_path() -> Path:
    return configs_dir() / "webui_secret"


def ensure_webui_secret() -> str:
    """Return a persistent secret for Open WebUI sessions."""
    secret_file = webui_secret_path()
    if secret_file.exists():
        return secret_file.read_text(encoding="utf-8").strip()
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(32)
    try:
        with secret_file.open("x", encoding="utf-8") as f:
            f.write(secret)
    except FileExistsError:
        return secret_file.read_text(encoding="utf-8").strip()
    return secret


def webui_admin_password_path() -> Path:
    """Return path to Open WebUI admin password file."""
    return configs_dir() / "webui_admin_password"


def ensure_webui_admin_password() -> str:
    """Generate and persist Open WebUI admin password."""
    password_file = webui_admin_password_path()
    if password_file.exists():
        return password_file.read_text(encoding="utf-8").strip()
    
    password_file.parent.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(24)
    
    try:
        with password_file.open("x", encoding="utf-8") as f:
            f.write(password)
        password_file.chmod(0o600)
    except FileExistsError:
        return password_file.read_text(encoding="utf-8").strip()
    
    return password
