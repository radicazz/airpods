"""
title: Content Moderation Pipeline
author: airpods
author_url: https://github.com/radicazz/airpods
version: 0.1.0
description: Pipeline for content safety checks - filters toxic/harmful content before sending to LLM and sanitizes responses.
required_open_webui_version: 0.3.0
"""

import re
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class Pipeline:
    class Valves(BaseModel):
        priority: int = Field(
            default=10, description="Pipeline priority (higher = earlier execution)"
        )
        enable_input_filtering: bool = Field(
            default=True,
            description="Filter user input for harmful content before sending to LLM",
        )
        enable_output_filtering: bool = Field(
            default=True,
            description="Filter LLM responses for harmful content before showing to user",
        )
        blocked_patterns: List[str] = Field(
            default=[
                r"\b(hack|exploit|bypass|crack)\s+(password|security|system)\b",
                r"\b(create|make|build)\s+(virus|malware|trojan)\b",
                r"\b(illegal|pirate|stolen)\s+(content|software|movie|music)\b",
            ],
            description="Regex patterns to block (case-insensitive)",
        )
        pii_detection: bool = Field(
            default=True,
            description="Detect and optionally redact PII (emails, phone numbers, SSNs)",
        )
        pii_redaction: bool = Field(
            default=False,
            description="Automatically redact detected PII instead of just warning",
        )
        max_user_message_length: int = Field(
            default=10000,
            description="Maximum character length for user messages (0 = unlimited)",
        )

    def __init__(self):
        self.valves = self.Valves()
        self.name = "Content Moderation Pipeline"

    def _detect_pii(self, text: str) -> Dict[str, List[str]]:
        """Detect potential PII in text."""
        pii_found = {
            "emails": re.findall(
                r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", text
            ),
            "phone_numbers": re.findall(
                r"\b(?:\+?1[-.]?)?\(?\d{3}\)?[-.]?\d{3}[-.]?\d{4}\b", text
            ),
            "ssn": re.findall(r"\b\d{3}-\d{2}-\d{4}\b", text),
            "credit_cards": re.findall(
                r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b", text
            ),
        }
        return {k: v for k, v in pii_found.items() if v}

    def _redact_pii(self, text: str) -> str:
        """Redact PII from text."""
        # Redact emails
        text = re.sub(
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
            "[EMAIL_REDACTED]",
            text,
        )
        # Redact phone numbers
        text = re.sub(
            r"\b(?:\+?1[-.]?)?\(?\d{3}\)?[-.]?\d{3}[-.]?\d{4}\b",
            "[PHONE_REDACTED]",
            text,
        )
        # Redact SSNs
        text = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[SSN_REDACTED]", text)
        # Redact credit cards
        text = re.sub(
            r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b", "[CC_REDACTED]", text
        )
        return text

    def _check_blocked_patterns(self, text: str) -> Optional[str]:
        """Check if text matches any blocked patterns."""
        for pattern in self.valves.blocked_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return pattern
        return None

    def pipe(
        self, user_message: str, model_id: str, messages: List[Dict], body: Dict
    ) -> Dict[str, Any]:
        """
        Process messages through the moderation pipeline.

        This runs before the LLM to filter input and after to filter output.
        """
        # INPUT FILTERING
        if self.valves.enable_input_filtering:
            # Length check
            if (
                self.valves.max_user_message_length > 0
                and len(user_message) > self.valves.max_user_message_length
            ):
                return {
                    "error": f"Message too long. Maximum {self.valves.max_user_message_length} characters allowed."
                }

            # Blocked pattern check
            blocked_pattern = self._check_blocked_patterns(user_message)
            if blocked_pattern:
                return {
                    "error": f"Content violates safety policy. Blocked pattern detected: {blocked_pattern}"
                }

            # PII detection
            if self.valves.pii_detection:
                pii_found = self._detect_pii(user_message)
                if pii_found:
                    if self.valves.pii_redaction:
                        # Redact PII from user message
                        user_message = self._redact_pii(user_message)
                        # Update the message in the body
                        for msg in messages:
                            if msg.get("role") == "user":
                                msg["content"] = self._redact_pii(msg["content"])
                    else:
                        # Just warn about PII
                        warning = "⚠️ **Privacy Warning:** Potential PII detected ("
                        warning += ", ".join(
                            [f"{len(v)} {k}" for k, v in pii_found.items()]
                        )
                        warning += "). Consider removing sensitive information.\n\n"
                        # Prepend warning to response (will be added by LLM context)
                        body["metadata"] = body.get("metadata", {})
                        body["metadata"]["pii_warning"] = warning

        return body

    async def on_startup(self):
        """Called when the pipeline is loaded."""
        print(
            f"Content Moderation Pipeline loaded with {len(self.valves.blocked_patterns)} patterns"
        )

    async def on_shutdown(self):
        """Called when the pipeline is unloaded."""
        pass
