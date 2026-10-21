"""
title: Echo Pipe
author: radicazz/airpods
author_url: https://github.com/radicazz/airpods
version: 1.0.0
description: Demonstrates a non-blocking Pipe with valves and optional status events.
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, Field


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content) if content is not None else ""

    parts = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


class Pipe:
    class Valves(BaseModel):
        prefix: str = Field(
            default="Echo: ", description="Prefix added to the generated response."
        )
        simulate_delay_seconds: float = Field(
            default=0,
            ge=0,
            le=5,
            description="Optional non-blocking demonstration delay in seconds.",
        )

    def __init__(self) -> None:
        self.valves = self.Valves()
        self.name = "Echo Pipe"

    async def pipe(
        self,
        body: dict,
        __user__: dict | None = None,
        __event_emitter__=None,
        __request__=None,
    ) -> str:
        if __event_emitter__ is not None:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {"description": "Preparing echo response", "done": False},
                }
            )

        if self.valves.simulate_delay_seconds:
            await asyncio.sleep(self.valves.simulate_delay_seconds)

        messages = body.get("messages")
        latest = ""
        if isinstance(messages, list):
            for message in reversed(messages):
                if isinstance(message, dict) and message.get("role") == "user":
                    latest = _content_text(message.get("content"))
                    break

        if __event_emitter__ is not None:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {"description": "Echo response ready", "done": True},
                }
            )

        return f"{self.valves.prefix}{latest or 'No user message received'}"
