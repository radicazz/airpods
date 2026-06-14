"""Image pull confirmation, live progress, and related UI helpers.

Extracted from the monolithic start command so the pull UX (pre-fetch,
download confirmation with disk checks, concurrent live layer progress
for podman/docker, and Ollama model pull progress) lives in one focused
module. Still depends on the cli manager proxy and rich console for now.
"""

from __future__ import annotations

import queue
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional

import typer
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.prompt import Confirm
from rich.table import Table

from airpods.logging import console, status_spinner
from airpods.ollama import format_size as _format_size
from airpods.services import ServiceSpec

from .common import format_transfer_label, manager


# Compiled once at import time — used inside the hot inner loop of
# _pull_images_with_progress to avoid repeated pattern compilation.
_LAYER_ID_RE = re.compile(r"^(?P<layer>[0-9a-f]{6,}):", re.IGNORECASE)
_DOWNLOAD_SIZE_RE = re.compile(
    r"(?P<cur>\d+(?:\.\d+)?)\s*(?P<cur_unit>[kKmMgGtTpP]?B)\s*/\s*"
    r"(?P<total>\d+(?:\.\d+)?)\s*(?P<total_unit>[kKmMgGtTpP]?B)"
)


def _parse_size_fragment(value: str, unit: str) -> int:
    multipliers = {
        "B": 1,
        "KB": 1024,
        "MB": 1024**2,
        "GB": 1024**3,
        "TB": 1024**4,
        "PB": 1024**5,
    }
    try:
        num = float(value)
    except ValueError:
        return 0
    factor = multipliers.get(unit.upper())
    if factor is None:
        return 0
    return int(num * factor)


def _confirm_image_downloads(specs: list[ServiceSpec]) -> bool:
    """Check for images to download and confirm with user.

    Returns True to proceed, False to cancel.
    """
    # Collect images that need to be downloaded
    to_download: list[tuple[str, str, int]] = []  # (service, image, size_bytes)

    with status_spinner("Checking images"):
        for spec in specs:
            # Check if image already exists locally
            if manager.runtime.image_exists(spec.image):
                continue

            # Try to get remote image size
            size_bytes = manager.runtime.get_remote_image_size(spec.image)

            # If we couldn't get size, use a placeholder
            if size_bytes is None:
                size_bytes = 0  # Will be marked as unknown

            to_download.append((spec.name, spec.image, size_bytes))

    # If no downloads needed, proceed
    if not to_download:
        return True

    # Get available disk space
    try:
        stat = shutil.disk_usage("/var/lib/containers")
    except (OSError, FileNotFoundError):
        # Fallback to root filesystem
        try:
            stat = shutil.disk_usage("/")
        except (OSError, FileNotFoundError):
            stat = None

    # Calculate total download size
    total_bytes = sum(size for _, _, size in to_download if size > 0)
    has_unknown_sizes = any(size == 0 for _, _, size in to_download)

    # Create borderless table
    table = Table(show_header=True, show_edge=False, show_lines=False, padding=(0, 2))
    table.add_column("Service", style="cyan", no_wrap=True)
    table.add_column("Image", style="dim")
    table.add_column("Size", justify="right", style="yellow")

    for service, image, size_bytes in to_download:
        # Truncate long image names
        display_image = image
        if len(display_image) > 45:
            display_image = f"{display_image[:42]}..."

        size_str = _format_size(size_bytes) if size_bytes > 0 else "unknown"
        table.add_row(service, display_image, size_str)

    console.print()
    console.print("[bold]Images to download:[/]")
    console.print(table)
    console.print()

    # Show total and available space
    if total_bytes > 0 and has_unknown_sizes:
        console.print(
            f"Total download: [yellow]at least {_format_size(total_bytes)}[/] (some sizes unknown)"
        )
    elif total_bytes > 0:
        console.print(f"Total download: [yellow]{_format_size(total_bytes)}[/]")
    elif has_unknown_sizes:
        console.print("Total download: [dim]unknown (size lookup failed)[/]")

    if stat:
        available = stat.free
        console.print(f"Available space: [green]{_format_size(available)}[/]")

        # Warn if insufficient space (with 10% buffer)
        if total_bytes > 0 and total_bytes * 1.1 > available:
            console.print(f"[warn]⚠ Warning: Download may exceed available space[/]")
    console.print()

    # Prompt for confirmation
    try:
        return Confirm.ask("Proceed with download?", default=True)
    except (KeyboardInterrupt, EOFError):
        console.print()
        return False


@dataclass(frozen=True)
class _PullEvent:
    kind: str
    task_id: int
    payload: str = ""


def _pull_images_with_progress(
    specs: list[ServiceSpec], *, max_concurrent: int, verbose: bool = False
) -> None:
    if not specs:
        console.print("[warn]No services enabled; nothing to initialize.[/]")
        return

    events: queue.Queue[_PullEvent] = queue.Queue()
    max_workers = max(1, max_concurrent)

    def _iter_pull_lines(stream: str):
        # Podman may emit carriage-return progress; normalize to line events.
        for chunk in stream.splitlines():
            for part in chunk.split("\r"):
                line = part.strip()
                if line:
                    yield line

    def _parse_download_progress(line: str) -> tuple[str, int, int | None] | None:
        # Expected patterns (docker/podman):
        # <layer>: Downloading 12.3MB/45.6MB
        # <layer>: Downloading [==>] 12.3MB/45.6MB
        match = _LAYER_ID_RE.match(line)
        if not match:
            return None
        layer = match.group("layer")
        size_match = _DOWNLOAD_SIZE_RE.search(line)
        if not size_match:
            return None
        current = _parse_size_fragment(
            size_match.group("cur"), size_match.group("cur_unit")
        )
        total = _parse_size_fragment(
            size_match.group("total"), size_match.group("total_unit")
        )
        if current <= 0:
            return None
        return layer, current, total if total > 0 else None

    def _is_noise_line(line: str) -> bool:
        lower = line.lower()
        return lower.startswith(
            (
                "copying blob",
                "copying",
                "pulling fs layer",
                "waiting",
                "extracting",
                "download complete",
                "pull complete",
                "already exists",
                "status:",
                "digest:",
            )
        )

    def _pull_one(spec: ServiceSpec, task_id: int) -> None:
        start = time.perf_counter()
        events.put(_PullEvent("start", task_id))
        runtime_cli = manager.runtime.runtime_name
        try:
            proc = subprocess.Popen(
                [runtime_cli, "pull", spec.image],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except OSError as exc:
            events.put(_PullEvent("error", task_id, str(exc)))
            return
        output: list[str] = []
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                output.append(raw)
                for line in _iter_pull_lines(raw):
                    events.put(_PullEvent("line", task_id, line))
        finally:
            rc = proc.wait()

        if rc != 0:
            detail = "".join(output).strip()
            events.put(_PullEvent("error", task_id, detail))
            return

        elapsed = time.perf_counter() - start
        size = manager.runtime.image_size(spec.image)
        transfer = format_transfer_label(size, elapsed) or f"{elapsed:.1f}s"
        events.put(_PullEvent("done", task_id, transfer))

    title = "[info]Pulling Images"
    if verbose:
        title = "[info]Pulling Images (live)"

    with Progress(
        SpinnerColumn(style="accent"),
        TextColumn("{task.fields[service]}", style="cyan", justify="right"),
        TextColumn("{task.fields[status]}", style="muted", markup=True),
        TextColumn("{task.fields[transfer]}", style="dim", justify="right"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        tasks: dict[int, ServiceSpec] = {}
        task_ids: dict[str, int] = {}
        progress_bytes: dict[int, dict[str, int]] = {}
        progress_totals: dict[int, dict[str, int]] = {}

        for spec in specs:
            task_id = progress.add_task(
                title,
                total=None,
                service=spec.name,
                status="Waiting…",
                transfer="",
            )
            tasks[task_id] = spec
            task_ids[spec.name] = task_id
            progress_bytes[task_id] = {}
            progress_totals[task_id] = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(_pull_one, spec, task_ids[spec.name]) for spec in specs
            ]

            failures: list[tuple[str, str]] = []
            done_count = 0
            while done_count < len(specs):
                try:
                    event = events.get(timeout=0.1)
                except queue.Empty:
                    continue

                if event.kind == "start":
                    progress.update(event.task_id, status="Pulling…", transfer="")
                elif event.kind == "line":
                    # Keep status compact; podman emits a lot of noise.
                    line = event.payload
                    parsed = _parse_download_progress(line)
                    if parsed is not None:
                        layer, current, total = parsed
                        progress_bytes[event.task_id][layer] = current
                        if total is not None:
                            progress_totals[event.task_id][layer] = total
                        downloaded = sum(progress_bytes[event.task_id].values())
                        if downloaded > 0:
                            total_known = sum(progress_totals[event.task_id].values())
                            if total_known > 0:
                                transfer = (
                                    f"Downloaded {_format_size(downloaded)}"
                                    f"/{_format_size(total_known)}"
                                )
                            else:
                                transfer = f"Downloaded {_format_size(downloaded)}"
                            progress.update(event.task_id, transfer=transfer)
                        continue
                    if _is_noise_line(line):
                        continue
                    if len(line) > 80:
                        line = f"{line[:77]}…"
                    progress.update(event.task_id, status=line)
                elif event.kind == "done":
                    progress.update(
                        event.task_id,
                        status="[ok]✓ Ready[/]",
                        transfer=event.payload,
                        total=1,
                        completed=1,
                    )
                    done_count += 1
                elif event.kind == "error":
                    spec = tasks.get(event.task_id)
                    failures.append((spec.name if spec else "unknown", event.payload))
                    progress.update(
                        event.task_id,
                        status="[error]✗ Failed[/]",
                        transfer="",
                        total=1,
                        completed=1,
                    )
                    done_count += 1

            for future in futures:
                future.result()

        if failures:
            for name, detail in failures:
                if detail:
                    trimmed = detail.strip()
                    if len(trimmed) > 500:
                        trimmed = f"{trimmed[:500]}…"
                    console.print(f"[error]{name} pull error:[/] {trimmed}")
                    if (
                        "manifest unknown" in trimmed
                        and "llama.cpp:server-cuda" in trimmed
                    ):
                        console.print(
                            "[info]Tip: switch to ghcr.io/ggml-org/llama.cpp:server "
                            "and let airpods derive the CUDA tag.[/]"
                        )
                else:
                    console.print(f"[error]{name} pull error:[/] unknown error")
            console.print("[error]✗ Failed to pull one or more images[/]")
            raise typer.Exit(code=1)


def _pull_ollama_model_with_progress(model_name: str, port: int, ollama_module) -> None:
    """Pull a single Ollama model, showing a live Rich progress bar."""
    with Progress(
        SpinnerColumn(style="accent"),
        TextColumn(f"  [accent]{model_name}[/]", justify="right"),
        TextColumn("{task.fields[status]}", style="muted", markup=True),
        TextColumn("{task.fields[transfer]}", style="dim", justify="right"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task_id = progress.add_task(
            "pull",
            total=None,
            status="connecting…",
            transfer="",
        )

        def on_progress(data: dict) -> None:
            status = (data.get("status") or "").strip()
            completed = data.get("completed") or 0
            total = data.get("total") or 0

            if total > 0:
                xfer = f"{_format_size(completed)}/{_format_size(total)}"
            elif completed > 0:
                xfer = _format_size(completed)
            else:
                xfer = ""

            if not status and not xfer:
                return  # Heartbeat with no useful content; keep current display

            if len(status) > 50:
                status = f"{status[:49]}…"

            progress.update(task_id, status=status, transfer=xfer)

        ollama_module.pull_model(model_name, port, progress_callback=on_progress)

        progress.update(
            task_id,
            status="[ok]✓ Ready[/]",
            transfer="",
            total=1,
            completed=1,
        )

    console.print(f"  [ok]✓ {model_name} ready[/]")
