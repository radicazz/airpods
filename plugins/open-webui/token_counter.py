"""
title: Token Counter
author: airpods
author_url: https://github.com/radicazz/airpods
version: 0.1.0
description: Counts and limits tokens in conversations with basic estimation.
"""

from pydantic import BaseModel, Field
from typing import Optional


class Filter:
    class Valves(BaseModel):
        priority: int = Field(
            default=0, description="Priority level for the filter operations."
        )
        max_tokens: int = Field(
            default=4000, description="Maximum tokens allowed per request."
        )
        warn_at_percentage: int = Field(
            default=80, description="Warn when token usage exceeds this percentage."
        )
        show_count: bool = Field(
            default=True, description="Add token count info to system messages."
        )

    def __init__(self):
        self.valves = self.Valves()

    def _estimate_tokens(self, text: str) -> int:
        """Rough estimation: ~4 characters per token on average."""
        return len(text) // 4

    def _count_conversation_tokens(self, messages: list) -> int:
        total = 0
        for message in messages:
            content = message.get("content", "")
            total += self._estimate_tokens(content)
            total += 4  # Overhead per message
        return total

    def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        messages = body.get("messages", [])
        token_count = self._count_conversation_tokens(messages)

        if token_count > self.valves.max_tokens:
            raise Exception(
                f"Token limit exceeded: {token_count}/{self.valves.max_tokens} tokens"
            )

        warning_threshold = (
            self.valves.max_tokens * self.valves.warn_at_percentage
        ) // 100
        if self.valves.show_count and token_count > warning_threshold:
            warning_msg = f"\n\n[Token usage: {token_count}/{self.valves.max_tokens} - {(token_count * 100) // self.valves.max_tokens}%]"

            system_msg = next((m for m in messages if m.get("role") == "system"), None)
            if system_msg:
                system_msg["content"] += warning_msg
            else:
                messages.insert(0, {"role": "system", "content": warning_msg})

        body["messages"] = messages
        return body
