"""Paths and transfers for files stored in managed directories."""

from __future__ import annotations

from http.client import HTTPException
import time
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from rich.progress import Progress

from airpods.logging import console


class DownloadError(RuntimeError):
    pass


def managed_path(root: Path, *parts: str) -> Path:
    """Resolve a relative destination, including existing symlink parents."""
    base = root.resolve()
    result = base
    for part in parts:
        path = Path(part)
        if path.is_absolute() or ".." in path.parts or "\\" in part:
            raise ValueError("path must stay within its managed directory")
        result = result / path
    result = result.resolve()
    if result == base or not result.is_relative_to(base):
        raise ValueError("path must stay within its managed directory")
    return result


def validate_component(value: str) -> str:
    if not value or value in {".", ".."} or any(c in value for c in "/\\"):
        raise ValueError("name must be a single filename or directory name")
    return value


class SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).scheme not in {"http", "https"}:
            raise HTTPError(
                newurl, code, "only http(s) redirects are supported", headers, fp
            )
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            old = urlparse(req.full_url)
            new = urlparse(newurl)
            if (old.scheme, old.hostname, old.port) != (
                new.scheme,
                new.hostname,
                new.port,
            ):
                redirected.remove_header("Authorization")
        return redirected


def open_url(request, *, timeout=300):
    return build_opener(SafeRedirectHandler()).open(request, timeout=timeout)


def download_file(
    url: str,
    dest: Path,
    *,
    hf_token: str | None = None,
    overwrite: bool = False,
    timeout_s: float = 300,
    retries: int = 2,
    opener=open_url,
    show_progress: bool = True,
) -> int:
    if dest.exists() and not overwrite:
        return dest.stat().st_size
    if timeout_s <= 0 or retries < 0:
        raise ValueError("timeout must be > 0 and retries must be >= 0")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("only http(s) urls are supported")
    headers = {"User-Agent": "airpods"}
    if hf_token and parsed.scheme == "https" and parsed.hostname == "huggingface.co":
        headers["Authorization"] = f"Bearer {hf_token}"
    request = Request(url, headers=headers)
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_error = None
    for attempt in range(retries + 1):
        tmp = None
        try:
            with opener(request, timeout=float(timeout_s)) as response:
                length = response.headers.get("Content-Length")
                total = int(length) if length and length.isdigit() else None
                written = 0
                with Progress(console=console, disable=not show_progress) as progress:
                    task = progress.add_task(f"Downloading {dest.name}", total=total)
                    with tempfile.NamedTemporaryFile(
                        dir=dest.parent,
                        prefix=f".{dest.name}.",
                        suffix=".part",
                        delete=False,
                    ) as handle:
                        tmp = Path(handle.name)
                        while chunk := response.read(256 * 1024):
                            handle.write(chunk)
                            written += len(chunk)
                            progress.update(task, advance=len(chunk))
                if total is not None and written != total:
                    raise OSError(
                        f"incomplete download: expected {total} bytes, received {written}"
                    )
            tmp.replace(dest)
            return written
        except (HTTPError, URLError, OSError, HTTPException) as exc:
            last_error = exc
            if attempt < retries:
                console.print(
                    f"[warn]Download failed (attempt {attempt + 1}/{retries + 1}): {exc}[/]"
                )
                time.sleep(min(2**attempt, 5))
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
    raise DownloadError(f"download failed: {last_error}") from last_error
