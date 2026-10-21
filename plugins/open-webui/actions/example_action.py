"""
title: Conversation Stats
author: radicazz/airpods
author_url: https://github.com/radicazz/airpods
version: 1.0.0
description: Demonstrates an Action that appends conversation statistics to a selected message.
"""

from __future__ import annotations

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


class Action:
    class Valves(BaseModel):
        priority: int = Field(
            default=0,
            description="Button display order; lower-priority actions appear first.",
        )

    def __init__(self) -> None:
        self.valves = self.Valves()

    async def action(
        self,
        body: dict,
        __user__: dict | None = None,
        __event_emitter__=None,
        __event_call__=None,
        __model__=None,
    ) -> dict | None:
        messages = body.get("messages")
        message_id = body.get("id")
        if not isinstance(messages, list) or not message_id:
            if __event_emitter__ is not None:
                await __event_emitter__(
                    {
                        "type": "notification",
                        "data": {
                            "type": "warning",
                            "content": "Conversation statistics are unavailable for this message.",
                        },
                    }
                )
            return None

        selected = next(
            (
                message
                for message in reversed(messages)
                if isinstance(message, dict) and message.get("id") == message_id
            ),
            None,
        )
        selected_content = _content_text((selected or {}).get("content"))
        user_count = sum(
            1
            for message in messages
            if isinstance(message, dict) and message.get("role") == "user"
        )
        assistant_count = sum(
            1
            for message in messages
            if isinstance(message, dict) and message.get("role") == "assistant"
        )
        stats = (
            "**Conversation stats**\n\n"
            f"- Total messages: {len(messages)}\n"
            f"- User messages: {user_count}\n"
            f"- Assistant messages: {assistant_count}"
        )
        content = f"{selected_content}\n\n---\n\n{stats}" if selected_content else stats

        if __event_emitter__ is not None:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {"description": "Conversation stats added", "done": True},
                }
            )

        return {"messages": [{"id": message_id, "content": content}]}
