"""
title: Conversation Turn Limit
author: radicazz/airpods
author_url: https://github.com/radicazz/airpods
version: 1.0.0
description: Demonstrates a configurable filter that limits user turns without logging conversation data.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


def _valve_value(valves: Any, name: str, default: int) -> int:
    if isinstance(valves, dict):
        value = valves.get(name, default)
    else:
        value = getattr(valves, name, default)
    return int(value)


class Filter:
    class Valves(BaseModel):
        priority: int = Field(
            default=0,
            description="Execution order; lower-priority filters run first.",
        )
        max_turns: int = Field(
            default=8,
            ge=1,
            description="Maximum number of user messages allowed in a conversation.",
        )

    class UserValves(BaseModel):
        max_turns: int = Field(
            default=4,
            ge=1,
            description="Per-user turn limit, capped by the administrator setting.",
        )

    def __init__(self) -> None:
        self.valves = self.Valves()

    async def inlet(self, body: dict, __user__: dict | None = None) -> dict:
        messages = body.get("messages")
        if not isinstance(messages, list):
            return body

        user_valves = (__user__ or {}).get("valves")
        user_limit = _valve_value(user_valves, "max_turns", self.valves.max_turns)
        max_turns = min(user_limit, self.valves.max_turns)
        turn_count = sum(
            1
            for message in messages
            if isinstance(message, dict) and message.get("role") == "user"
        )

        if turn_count > max_turns:
            raise ValueError(
                f"Conversation turn limit exceeded: {turn_count}/{max_turns} user turns."
            )

        return body

    async def outlet(self, body: dict, __user__: dict | None = None) -> dict:
        return body
