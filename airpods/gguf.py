"""Utilities for managing GGUF model files."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse, unquote
from airpods.files import download_file, managed_path, open_url as urlopen

from airpods import state


def gguf_models_dir() -> Path:
    return state.resolve_volume_path("airpods_models/gguf")


def ensure_gguf_models_dir() -> Path:
    path = gguf_models_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def infer_filename(url: str) -> Optional[str]:
    parsed = urlparse(url)
    name = unquote(Path(parsed.path).name)
    return name or None


def download_model(url: str, *, name: Optional[str] = None) -> Tuple[Path, int]:
    dest_dir = gguf_models_dir()
    filename = name or infer_filename(url)
    if not filename:
        raise ValueError("Unable to infer filename from URL; use --name")
    dest = managed_path(dest_dir, filename)
    if dest.exists():
        raise FileExistsError(f"Model already exists: {dest}")
    size = download_file(url, dest, opener=urlopen, show_progress=False)
    return dest, size
