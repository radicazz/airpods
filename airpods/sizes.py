"""Shared binary byte-size formatting and label parsing."""

import re


def format_bytes(count: int, *, compact: bool = False) -> str:
    size = float(count)
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    number = f"{size:.1f}" if index or compact else str(int(size))
    return f"{number}{'' if compact else ' '}{units[index]}"


def parse_bytes(label: str | None) -> int | None:
    match = re.fullmatch(
        r"\s*(\d+(?:\.\d+)?)\s*([KMGTP]?)(?:I?B)\s*", label or "", re.IGNORECASE
    )
    if match is None:
        return None
    power = " KMGTP".index(match[2].upper()) if match[2] else 0
    return int(float(match[1]) * 1024**power)
