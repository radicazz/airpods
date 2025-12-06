"""
title: Code Detector
author: airpods
author_url: https://github.com/radicazz/airpods
version: 0.1.0
description: Detects code in user messages and adds helpful context for the AI.
"""

from pydantic import BaseModel, Field
from typing import Optional
import re


class Filter:
    class Valves(BaseModel):
        priority: int = Field(
            default=0, description="Priority level for the filter operations."
        )
        auto_detect_language: bool = Field(
            default=True, description="Automatically detect programming language."
        )
        add_code_context: bool = Field(
            default=True,
            description="Add context about code blocks to system message.",
        )

    def __init__(self):
        self.valves = self.Valves()
        self.language_patterns = {
            "python": [r"\bdef\b", r"\bclass\b", r"\bimport\b", r"\bfrom\b"],
            "javascript": [r"\bfunction\b", r"\bconst\b", r"\blet\b", r"=>"],
            "java": [r"\bpublic class\b", r"\bprivate\b", r"\bvoid\b"],
            "rust": [r"\bfn\b", r"\blet mut\b", r"\bimpl\b", r"\buse\b"],
            "go": [r"\bfunc\b", r"\bpackage\b", r":="],
            "c++": [r"#include", r"\bnamespace\b", r"\bstd::"],
        }

    def _detect_language(self, code: str) -> Optional[str]:
        scores = {}
        for lang, patterns in self.language_patterns.items():
            score = sum(1 for pattern in patterns if re.search(pattern, code))
            if score > 0:
                scores[lang] = score
        return max(scores.items(), key=lambda x: x[1])[0] if scores else None

    def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        messages = body.get("messages", [])

        code_blocks = []
        for message in messages:
            if message.get("role") == "user":
                content = message.get("content", "")

                matches = re.findall(r"```(\w+)?\n(.*?)```", content, re.DOTALL)
                for lang, code in matches:
                    detected_lang = (
                        lang
                        if lang
                        else (
                            self._detect_language(code)
                            if self.valves.auto_detect_language
                            else None
                        )
                    )
                    if detected_lang:
                        code_blocks.append(detected_lang)

        if code_blocks and self.valves.add_code_context:
            langs = ", ".join(set(code_blocks))
            context = f"User's message contains code in: {langs}. Provide detailed technical assistance."

            system_msg = next((m for m in messages if m.get("role") == "system"), None)
            if system_msg:
                system_msg["content"] += f"\n\n{context}"
            else:
                messages.insert(0, {"role": "system", "content": context})

        body["messages"] = messages
        return body
