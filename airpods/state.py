from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Optional, Union

STATE_ROOT_ENV = "AIRPODS_HOME"
_PROJECT_MARKERS = ("pyproject.toml", ".git")


def _detect_repo_root() -> Optional[Path]:
    start = Path(__file__).resolve()
    for parent in start.parents:
        if any((parent / marker).exists() for marker in _PROJECT_MARKERS):
            return parent
    return None


@lru_cache(maxsize=1)
def state_root() -> Path:
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


def configs_dir() -> Path:
    path = state_root() / "configs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_dir() -> Path:
    return configs_dir()


def ensure_config_dir() -> Path:
    return configs_dir()


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
    secret = secrets.token_urlsafe(32)
    secret_file.write_text(secret, encoding="utf-8")
    return secret
