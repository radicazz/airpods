"""
title: System Prompt Enforcer
author: airpods
author_url: https://github.com/radicazz/airpods
version: 0.1.0
description: Ensures a system prompt is always present and optionally prevents users from overriding it.
"""

from pydantic import BaseModel, Field
from typing import Optional


class Filter:
    class Valves(BaseModel):
        priority: int = Field(
            default=0, description="Priority level for the filter operations."
        )
        enforce_system_prompt: bool = Field(
            default=True,
            description="Always ensure a system prompt exists in the conversation.",
        )
        prevent_override: bool = Field(
            default=False,
            description="Prevent users from modifying the system prompt.",
        )
        default_system_prompt: str = Field(
            default="You are a helpful AI assistant.",
            description="Default system prompt if none exists.",
        )

    def __init__(self):
        self.valves = self.Valves()

    def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        messages = body.get("messages", [])

        if not messages:
            return body

        system_msg = next((m for m in messages if m.get("role") == "system"), None)

        if self.valves.enforce_system_prompt:
            if not system_msg:
                messages.insert(
                    0, {"role": "system", "content": self.valves.default_system_prompt}
                )
            elif self.valves.prevent_override:
                system_msg["content"] = self.valves.default_system_prompt

        body["messages"] = messages
        return body
