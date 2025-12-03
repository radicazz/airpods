from __future__ import annotations

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.theme import Theme


# One Dark-inspired palette tuned for Rich output
PALETTE = {
    "fg": "#abb2bf",
    "fg_muted": "#5c6370",
    "bg": "#1e222a",
    "bg_alt": "#21252b",
    "bg_offset": "#2c323c",
    "green": "#98c379",
    "yellow": "#e5c07b",
    "orange": "#d19a66",
    "blue": "#61afef",
    "cyan": "#56b6c2",
    "purple": "#c678dd",
    "red": "#e06c75",
}

_theme = Theme(
    {
        "text": PALETTE["fg"],
        "muted": PALETTE["fg_muted"],
        "accent": PALETTE["orange"],
        "ok": PALETTE["green"],
        "warn": PALETTE["yellow"],
        "error": f"bold {PALETTE['red']}",
        "info": PALETTE["blue"],
        "alias": PALETTE["purple"],
        "section": f"bold {PALETTE['orange']}",
    }
)

console = Console(theme=_theme, style=PALETTE["fg"])


def status_spinner(message: str):
    """Return a Rich status spinner context manager."""
    return console.status(f"[info]{message}[/]")


class StepProgress:
    """Progress helper that prefers spinners + counters unless streaming progress is available."""

    def __init__(self, message: str, total: int, *, streaming: bool = False):
        self.message = message
        self.total = total
        self.streaming = streaming
        self._progress: Progress | None = None
        self._task_id: int | None = None
        self._status = None

    def __enter__(self) -> "StepProgress":
        if self.streaming and self.total > 0:
            self._progress = Progress(
                SpinnerColumn(style="accent"),
                TextColumn("{task.description}", markup=True),
                BarColumn(bar_width=None),
                TextColumn("{task.completed}/{task.total}", style="muted"),
                TimeElapsedColumn(),
                console=console,
                transient=True,
            )
            self._progress.__enter__()
            self._task_id = self._progress.add_task(self.message, total=self.total)
        else:
            self._status = status_spinner(self.message)
            self._status.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._progress:
            self._progress.__exit__(exc_type, exc, tb)
        elif self._status:
            self._status.__exit__(exc_type, exc, tb)

    def start(self, index: int, detail: str | None = None) -> None:
        """Update the description for the current step."""
        description = self._format_description(index, detail)
        if self._progress and self._task_id is not None:
            self._progress.update(self._task_id, description=description)
        elif self._status:
            self._status.update(f"[info]{description}[/]")

    def advance(self) -> None:
        """Advance the progress indicator when a step finishes."""
        if self._progress and self._task_id is not None:
            self._progress.advance(self._task_id)

    def _format_description(self, index: int, detail: str | None) -> str:
        base = self.message
        if self.total > 0 and index:
            base = f"{base} ({index}/{self.total})"
        if detail:
            base = f"{base} — {detail}"
        return base


def step_progress(message: str, total: int, *, streaming: bool = False) -> StepProgress:
    """Return a StepProgress helper for consistent CLI progress indicators."""
    return StepProgress(message, total, streaming=streaming)
