from __future__ import annotations

from rich.console import Console
from rich.theme import Theme


_theme = Theme(
    {
        "ok": "green",
        "warn": "yellow",
        "error": "bold red",
        "info": "cyan",
    }
)

console = Console(theme=_theme)


def status_spinner(message: str):
    """Return a Rich status spinner context manager."""
    return console.status(f"[info]{message}[/]")
