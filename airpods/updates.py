from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Optional

import requests

from airpods import __version__
from airpods.state import configs_dir

_REPO = "radicazz/airpods"
_DEFAULT_CACHE_TTL_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class InstallSource:
    kind: str  # "nightly", "tag", "wheel_or_index"
    revision: Optional[str] = None


@dataclass(frozen=True)
class ReleaseInfo:
    tag: str
    version: str
    html_url: str


def _parse_version_tuple(value: str) -> tuple[int, int, int]:
    normalized = value.strip()
    if normalized.startswith("v"):
        normalized = normalized[1:]
    parts = normalized.split(".")
    major = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 0
    minor = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    patch = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    return (major, minor, patch)


def _cache_path() -> str:
    return str(configs_dir() / "update_check.json")


def detect_install_source() -> InstallSource:
    """Best-effort detection of how airpods was installed.

    If installed from git with PEP 610 metadata, we can tell whether the requested
    revision is `main` (nightly) or a tag (stable).
    """
    try:
        from importlib.metadata import distribution

        dist = distribution("airpods")
        direct_url_text = dist.read_text("direct_url.json")
        if not direct_url_text:
            return InstallSource(kind="wheel_or_index")
        data = json.loads(direct_url_text)
    except Exception:
        return InstallSource(kind="wheel_or_index")

    vcs_info = data.get("vcs_info") if isinstance(data, dict) else None
    if isinstance(vcs_info, dict):
        requested = vcs_info.get("requested_revision") or vcs_info.get("commit_id")
        if requested == "main":
            return InstallSource(kind="nightly", revision="main")
        if isinstance(requested, str) and requested.startswith("v"):
            return InstallSource(kind="tag", revision=requested)
        return InstallSource(
            kind="wheel_or_index", revision=str(requested) if requested else None
        )
    return InstallSource(kind="wheel_or_index")


def fetch_latest_release(*, timeout_seconds: float = 1.5) -> ReleaseInfo:
    """Fetch latest version from main branch pyproject.toml.

    This is more reliable than GitHub releases API since the project doesn't
    always create releases for every version bump.
    """
    url = f"https://raw.githubusercontent.com/{_REPO}/main/pyproject.toml"
    resp = requests.get(
        url,
        timeout=timeout_seconds,
        headers={"User-Agent": "airpods"},
    )
    resp.raise_for_status()

    # Parse version from pyproject.toml
    # Looking for: version = "0.19.1"
    content = resp.text
    version = None
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("version") and "=" in line:
            # Extract version string: version = "0.19.1" -> 0.19.1
            parts = line.split("=", 1)
            if len(parts) == 2:
                version_str = parts[1].strip().strip('"').strip("'")
                if version_str and version_str[0].isdigit():
                    version = version_str
                    break

    if not version:
        raise RuntimeError("could not parse version from pyproject.toml")

    tag = f"v{version}" if not version.startswith("v") else version
    html_url = f"https://github.com/{_REPO}/tree/main"

    return ReleaseInfo(tag=tag, version=version, html_url=html_url)


def check_for_update(
    *,
    timeout_seconds: float = 1.5,
    cache_ttl_seconds: int = _DEFAULT_CACHE_TTL_SECONDS,
    force: bool = False,
    interactive_only: bool = True,
) -> Optional[ReleaseInfo]:
    """Return latest release info, using a small cache to avoid repeated network calls.

    Returns None if update checks are disabled or if the network request fails.
    """
    if interactive_only and not sys.stdout.isatty():
        return None

    flag = os.environ.get("AIRPODS_NO_UPDATE_CHECK", "").strip().lower()
    if flag not in {"", "0", "false"}:
        return None

    path = _cache_path()
    now = int(time.time())

    if not force:
        try:
            with open(path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            checked_at = int(cached.get("checked_at") or 0)
            if checked_at and (now - checked_at) < cache_ttl_seconds:
                tag = str(cached.get("tag") or "").strip()
                version = str(cached.get("version") or "").strip()
                html_url = str(cached.get("html_url") or "").strip()
                if tag and version:
                    return ReleaseInfo(tag=tag, version=version, html_url=html_url)
        except Exception:
            pass

    try:
        latest = fetch_latest_release(timeout_seconds=timeout_seconds)
    except Exception:
        return None

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "checked_at": now,
                    "tag": latest.tag,
                    "version": latest.version,
                    "html_url": latest.html_url,
                },
                f,
            )
    except Exception:
        pass
    return latest


def is_update_available(latest: ReleaseInfo) -> bool:
    return _parse_version_tuple(latest.version) > _parse_version_tuple(__version__)


def format_upgrade_hint(
    latest: ReleaseInfo, source: Optional[InstallSource] = None
) -> str:
    src = source or detect_install_source()
    if src.kind == "nightly":
        return "Run `uv tool upgrade airpods` to update."
    return f'Run `uv tool install --upgrade "git+https://github.com/{_REPO}.git@{latest.tag}"` to update.'
