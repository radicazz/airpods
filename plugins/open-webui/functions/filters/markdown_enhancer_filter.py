"""
title: Markdown Content Enhancer
author: airpods
author_url: https://github.com/radicazz/airpods
version: 0.1.0
description: Enhances AI responses by adding custom UI elements like collapsible sections, info boxes, and code formatting.
required_open_webui_version: 0.3.0
"""

import re
from pydantic import BaseModel, Field
from typing import Optional


class Filter:
    class Valves(BaseModel):
        priority: int = Field(
            default=5, description="Priority level for the filter operations."
        )
        enable_collapsible: bool = Field(
            default=True,
            description="Enable collapsible sections for long content (:::details syntax)",
        )
        enable_info_boxes: bool = Field(
            default=True,
            description="Convert [INFO], [WARNING], [ERROR] markers into styled boxes",
        )
        enable_code_metadata: bool = Field(
            default=True,
            description="Add metadata badges to code blocks (language, line count)",
        )
        max_code_lines_before_collapse: int = Field(
            default=50,
            description="Automatically make code blocks collapsible if they exceed this line count",
        )

    def __init__(self):
        self.valves = self.Valves()

    def _enhance_code_blocks(self, content: str) -> str:
        """Add metadata and auto-collapse to code blocks."""
        if not self.valves.enable_code_metadata:
            return content

        def process_code_block(match):
            lang = match.group(1) or "text"
            code = match.group(2)
            lines = code.strip().split("\n")
            line_count = len(lines)

            # Add metadata badge
            metadata = f"*{lang.upper()} • {line_count} lines*\n\n"

            # Auto-collapse long code
            if (
                self.valves.max_code_lines_before_collapse > 0
                and line_count > self.valves.max_code_lines_before_collapse
            ):
                return f"\n:::details View {lang.upper()} code ({line_count} lines)\n{metadata}```{lang}\n{code}```\n:::\n"

            return f"\n{metadata}```{lang}\n{code}```\n"

        # Match ```language\ncode\n```
        pattern = r"```(\w*)\n(.*?)```"
        return re.sub(pattern, process_code_block, content, flags=re.DOTALL)

    def _enhance_info_boxes(self, content: str) -> str:
        """Convert [INFO], [WARNING], [ERROR] markers into styled boxes."""
        if not self.valves.enable_info_boxes:
            return content

        replacements = {
            r"\[INFO\](.*?)(?=\n\n|\n\[|$)": r"> 💡 **Info:**\1",
            r"\[WARNING\](.*?)(?=\n\n|\n\[|$)": r"> ⚠️ **Warning:**\1",
            r"\[ERROR\](.*?)(?=\n\n|\n\[|$)": r"> ❌ **Error:**\1",
            r"\[TIP\](.*?)(?=\n\n|\n\[|$)": r"> ✨ **Tip:**\1",
            r"\[NOTE\](.*?)(?=\n\n|\n\[|$)": r"> 📝 **Note:**\1",
        }

        for pattern, replacement in replacements.items():
            content = re.sub(pattern, replacement, content, flags=re.DOTALL)

        return content

    def outlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        """Process AI response to add UI enhancements."""
        messages = body.get("messages", [])

        for message in messages:
            if message.get("role") == "assistant":
                content = message.get("content", "")

                # Apply enhancements in order
                content = self._enhance_info_boxes(content)
                content = self._enhance_code_blocks(content)

                message["content"] = content

        body["messages"] = messages
        return body
