"""
title: Profanity Filter
author: airpods
author_url: https://github.com/radicazz/airpods
version: 0.1.0
description: Filters profanity from user messages and optionally from AI responses.
"""

from pydantic import BaseModel, Field
from typing import Optional
import re


class Filter:
    class Valves(BaseModel):
        priority: int = Field(
            default=0, description="Priority level for the filter operations."
        )
        filter_input: bool = Field(
            default=True, description="Filter profanity from user input."
        )
        filter_output: bool = Field(
            default=False, description="Filter profanity from AI responses."
        )
        block_on_profanity: bool = Field(
            default=False,
            description="Block the request entirely if profanity is detected.",
        )
        replacement_text: str = Field(
            default="[filtered]", description="Text to replace profanity with."
        )

    def __init__(self):
        self.valves = self.Valves()
        self.profanity_patterns = [
            r"\bf+u+c+k+\w*",
            r"\bs+h+i+t+\w*",
            r"\bd+a+m+n+\w*",
            r"\ba+s+s+h+o+l+e+\w*",
            r"\bb+i+t+c+h+\w*",
        ]

    def _contains_profanity(self, text: str) -> bool:
        text_lower = text.lower()
        return any(
            re.search(pattern, text_lower) for pattern in self.profanity_patterns
        )

    def _filter_text(self, text: str) -> str:
        result = text
        for pattern in self.profanity_patterns:
            result = re.sub(
                pattern, self.valves.replacement_text, result, flags=re.IGNORECASE
            )
        return result

    def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        if not self.valves.filter_input:
            return body

        messages = body.get("messages", [])

        for message in messages:
            if message.get("role") == "user":
                content = message.get("content", "")
                if self.valves.block_on_profanity and self._contains_profanity(content):
                    raise Exception("Your message contains inappropriate language.")
                message["content"] = self._filter_text(content)

        body["messages"] = messages
        return body

    def outlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        if not self.valves.filter_output:
            return body

        messages = body.get("messages", [])

        for message in messages:
            if message.get("role") == "assistant":
                content = message.get("content", "")
                message["content"] = self._filter_text(content)

        body["messages"] = messages
        return body
