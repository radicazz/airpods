"""Utilities for managing GGUF model files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import quote, urlparse, unquote
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


DEFAULT_QUANT = "Q4_K_M"

_HF_SPEC_RE = re.compile(r"^([A-Za-z0-9][\w.-]*)/([A-Za-z0-9][\w.-]*)(?::([\w.-]+))?$")
_SHARD_RE = re.compile(r"-\d{5}-of-\d{5}(?=\.gguf$)", re.IGNORECASE)


def parse_hf_spec(spec: str) -> Optional[Tuple[str, Optional[str]]]:
    """Parse ``owner/repo[:QUANT]`` (llama.cpp ``-hf`` style) into (repo, quant).

    Returns None for URLs and anything that is not a HuggingFace repo spec.
    """
    value = spec.strip()
    if "://" in value:
        return None
    for prefix in ("hf.co/", "huggingface.co/"):
        if value.lower().startswith(prefix):
            value = value[len(prefix) :]
            break
    match = _HF_SPEC_RE.match(value)
    if not match:
        return None
    return f"{match.group(1)}/{match.group(2)}", match.group(3)


def hf_file_url(repo: str, path: str, revision: str = "main") -> str:
    return f"https://huggingface.co/{repo}/resolve/{revision}/{quote(path)}"


def is_mmproj(path: str) -> bool:
    return "mmproj" in Path(path).name.lower()


def group_model_files(files: List[dict]) -> List[List[dict]]:
    """Group non-mmproj GGUF files, keeping split shards together."""
    groups: dict[str, List[dict]] = {}
    for entry in files:
        if is_mmproj(entry["filename"]):
            continue
        key = _SHARD_RE.sub("", entry["filename"])
        groups.setdefault(key, []).append(entry)
    return [sorted(g, key=lambda e: e["filename"]) for g in groups.values()]


def match_quant(groups: List[List[dict]], quant: str) -> List[List[dict]]:
    """Return groups whose filename contains ``quant`` as a whole token."""
    pattern = re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(quant)}(?![A-Za-z0-9_])", re.IGNORECASE
    )
    return [g for g in groups if pattern.search(Path(g[0]["filename"]).name)]


def mmproj_files(files: List[dict]) -> List[dict]:
    return [f for f in files if is_mmproj(f["filename"])]


def download_hf_file(
    repo: str, path: str, *, name: Optional[str] = None, hf_token: Optional[str] = None
) -> Tuple[Path, int]:
    """Download one file from a HuggingFace repo into the GGUF store."""
    dest = managed_path(gguf_models_dir(), name or Path(path).name)
    if dest.exists():
        raise FileExistsError(f"Model already exists: {dest}")
    size = download_file(
        hf_file_url(repo, path),
        dest,
        hf_token=hf_token,
        opener=urlopen,
        show_progress=True,
    )
    return dest, size


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
