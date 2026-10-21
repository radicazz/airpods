"""
title: Vision Router
author: radicazz/airpods
version: 1.0.0
description: Caption image inputs with a configured vision model before forwarding them to a text-only model.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field


def _now() -> float:
    return time.time()


def _get_attr(value: Any, name: str, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _user_valves(user: dict | None) -> Any:
    return user.get("valves") if isinstance(user, dict) else None


def _last_user_parts(messages: list[dict]) -> tuple[int | None, str, list[dict]]:
    """Return the final user-message index, its text, and valid image blocks."""
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            return index, content, []
        if not isinstance(content, list):
            return index, "", []

        texts: list[str] = []
        images: list[dict] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text" and isinstance(part.get("text"), str):
                texts.append(part["text"])
            elif part.get("type") == "image_url":
                image_url = part.get("image_url")
                if isinstance(image_url, dict) and isinstance(
                    image_url.get("url"), str
                ):
                    images.append(
                        {"type": "image_url", "image_url": {"url": image_url["url"]}}
                    )
        return index, "\n".join(texts).strip(), images
    return None, "", []


def _strip_images(message: dict) -> None:
    content = message.get("content")
    if not isinstance(content, list):
        return
    texts = [
        part["text"]
        for part in content
        if isinstance(part, dict)
        and part.get("type") == "text"
        and isinstance(part.get("text"), str)
    ]
    message["content"] = "\n".join(texts).strip()


def _format(template: str, **values: Any) -> str:
    for name, value in values.items():
        template = template.replace("{" + name + "}", str(value))
    return template


def _http_post_json(url: str, payload: dict, timeout_seconds: int) -> dict:
    request = Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            result = json.loads(response.read().decode(errors="replace") or "{}")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Vision model request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("Vision model returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Vision model returned an unexpected response")
    return result


@dataclass
class _CacheEntry:
    value: str
    expires_at: float


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=0, description="Filter priority.")
        enabled: bool = Field(default=True, description="Enable this filter.")
        ollama_openai_base_url: str = Field(
            default="http://localhost:11434/v1",
            description="Base URL for Ollama's OpenAI-compatible API.",
        )
        vision_timeout_seconds: int = Field(default=90, ge=1, le=600)
        default_vision_model_id: str = Field(
            default="",
            description="Fallback vision model ID, such as joycaption:latest.",
        )
        vision_system_prompt: str = ""
        vision_user_prompt_template: str = Field(
            default="{user_text}", description="Supports {user_text} and {n_images}."
        )
        injection_mode: Literal["system_message", "prepend_user", "append_user"] = (
            "system_message"
        )
        injection_template: str = Field(
            default="[Image analysis via {vision_model}]\n{caption}",
            description="Supports {caption}, {vision_model}, and {n_images}.",
        )
        strip_images_from_text_request: bool = True
        skip_when_target_is_vision_model: bool = True
        multi_image_strategy: Literal["single_call", "per_image", "first_only"] = (
            "single_call"
        )
        max_caption_chars: int = Field(default=8000, ge=0)
        cache_enabled: bool = True
        cache_ttl_seconds: int = Field(default=600, ge=1)
        cache_max_entries: int = Field(default=128, ge=1, le=2048)
        target_model_allow_regex: str = Field(
            default=".*",
            description="Only run when the target model matches this regex.",
        )

    class UserValves(BaseModel):
        enabled: bool = True
        vision_model_id: str = Field(
            default="", description="Per-user vision model ID."
        )

    def __init__(self) -> None:
        self.valves = self.Valves()
        self._cache: dict[str, _CacheEntry] = {}

    def _vision_model(self, user: dict | None) -> str:
        selected = _get_attr(_user_valves(user), "vision_model_id", "")
        return str(selected or self.valves.default_vision_model_id).strip()

    def _cache_get(self, key: str) -> str | None:
        if not self.valves.cache_enabled:
            return None
        entry = self._cache.get(key)
        if entry is None:
            return None
        if entry.expires_at <= _now():
            self._cache.pop(key, None)
            return None
        return entry.value

    def _cache_put(self, key: str, value: str) -> None:
        if not self.valves.cache_enabled:
            return
        now = _now()
        self._cache = {
            cache_key: entry
            for cache_key, entry in self._cache.items()
            if entry.expires_at > now
        }
        while len(self._cache) >= self.valves.cache_max_entries:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = _CacheEntry(
            value=value, expires_at=now + self.valves.cache_ttl_seconds
        )

    async def _call_vision_model(
        self, vision_model: str, prompt: str, images: list[dict]
    ) -> str:
        messages: list[dict] = []
        if self.valves.vision_system_prompt:
            messages.append(
                {"role": "system", "content": self.valves.vision_system_prompt}
            )
        messages.append(
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}, *images],
            }
        )
        response = await asyncio.to_thread(
            _http_post_json,
            f"{self.valves.ollama_openai_base_url.rstrip('/')}/chat/completions",
            {"model": vision_model, "messages": messages, "stream": False},
            self.valves.vision_timeout_seconds,
        )
        choices = response.get("choices")
        if (
            not isinstance(choices, list)
            or not choices
            or not isinstance(choices[0], dict)
        ):
            raise RuntimeError("Vision model response did not include a completion")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise RuntimeError("Vision model response did not include a message")
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                part["text"]
                for part in content
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            ).strip()
        raise RuntimeError("Vision model response did not include text content")

    async def inlet(self, body: dict, __user__: dict | None = None) -> dict:
        if not self.valves.enabled or not bool(
            _get_attr(_user_valves(__user__), "enabled", True)
        ):
            return body
        model_id = str(body.get("model") or "").strip()
        try:
            if not re.match(self.valves.target_model_allow_regex, model_id):
                return body
        except re.error:
            pass

        messages = body.get("messages")
        if not isinstance(messages, list):
            return body
        index, user_text, images = _last_user_parts(messages)
        if index is None or not images:
            return body
        vision_model = self._vision_model(__user__)
        if not vision_model or (
            self.valves.skip_when_target_is_vision_model and model_id == vision_model
        ):
            return body

        image_count = len(images)
        prompt = _format(
            self.valves.vision_user_prompt_template,
            user_text=user_text,
            n_images=image_count,
        ).strip()
        cache_key = hashlib.sha256(
            json.dumps(
                {
                    "model": vision_model,
                    "urls": [image["image_url"]["url"] for image in images],
                    "prompt": prompt,
                    "strategy": self.valves.multi_image_strategy,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        caption = self._cache_get(cache_key)
        if caption is None:
            if self.valves.multi_image_strategy == "first_only":
                caption = await self._call_vision_model(
                    vision_model, prompt, images[:1]
                )
            elif self.valves.multi_image_strategy == "per_image":
                captions = [
                    await self._call_vision_model(
                        vision_model,
                        f"{prompt}\n\n(Image {number} of {image_count})",
                        [image],
                    )
                    for number, image in enumerate(images, start=1)
                ]
                caption = "\n\n".join(item.strip() for item in captions if item.strip())
            else:
                caption = await self._call_vision_model(vision_model, prompt, images)
            caption = caption.strip()
            if (
                self.valves.max_caption_chars
                and len(caption) > self.valves.max_caption_chars
            ):
                caption = caption[: self.valves.max_caption_chars].rstrip() + "…"
            self._cache_put(cache_key, caption)

        injection = _format(
            self.valves.injection_template,
            caption=caption,
            vision_model=vision_model,
            n_images=image_count,
        ).strip()
        user_message = messages[index]
        if self.valves.strip_images_from_text_request:
            _strip_images(user_message)
        if self.valves.injection_mode == "system_message":
            messages.insert(index, {"role": "system", "content": injection})
        else:
            existing = user_message.get("content")
            text = existing if isinstance(existing, str) else user_text
            if self.valves.injection_mode == "prepend_user":
                user_message["content"] = f"{injection}\n\n{text}".strip()
            else:
                user_message["content"] = f"{text}\n\n{injection}".strip()
        return body
