"""
title: Vision via JoyCaption
author: airpods
author_url: https://github.com/radicazz/airpods
version: 0.1.0
description: Routes image inputs through JoyCaption API for models without native vision support.
"""

from pydantic import BaseModel, Field
from typing import Optional
import requests
import base64


class Filter:
    class Valves(BaseModel):
        priority: int = Field(
            default=-1, description="Priority level (negative = early execution)."
        )
        joycaption_url: str = Field(
            default="http://localhost:5000/caption",
            description="JoyCaption API endpoint URL.",
        )
        joycaption_timeout: int = Field(
            default=30, description="Request timeout in seconds."
        )
        vision_models: list[str] = Field(
            default=[
                "llava",
                "bakllava",
                "llava-llama3",
                "llava-phi3",
                "moondream",
            ],
            description="Model names that have native vision support (skip processing).",
        )
        auto_inject_captions: bool = Field(
            default=True,
            description="Automatically inject image captions into user messages.",
        )
        caption_prefix: str = Field(
            default="[Image description: ", description="Prefix for image captions."
        )
        caption_suffix: str = Field(
            default="]", description="Suffix for image captions."
        )

    def __init__(self):
        self.valves = self.Valves()

    def _model_has_vision(self, model: str) -> bool:
        """Check if the model has native vision support."""
        model_lower = model.lower()
        return any(vm in model_lower for vm in self.valves.vision_models)

    def _extract_images_from_message(self, message: dict) -> list[str]:
        """Extract base64 images from message content."""
        images = []
        content = message.get("content", "")

        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "image_url":
                    image_url = item.get("image_url", {})
                    if isinstance(image_url, dict):
                        url = image_url.get("url", "")
                    else:
                        url = image_url
                    if url.startswith("data:image/"):
                        images.append(url.split(",", 1)[1] if "," in url else url)
        return images

    def _caption_image(self, image_b64: str) -> Optional[str]:
        """Send image to JoyCaption and get description."""
        try:
            response = requests.post(
                self.valves.joycaption_url,
                json={"image": image_b64},
                timeout=self.valves.joycaption_timeout,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("caption", data.get("description"))
        except Exception as e:
            print(f"JoyCaption error: {e}")
            return None

    def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        model = body.get("model", "")

        if self._model_has_vision(model):
            return body

        messages = body.get("messages", [])
        modified = False

        for message in messages:
            if message.get("role") == "user":
                images = self._extract_images_from_message(message)

                if images and self.valves.auto_inject_captions:
                    captions = []
                    for img_b64 in images:
                        caption = self._caption_image(img_b64)
                        if caption:
                            captions.append(
                                f"{self.valves.caption_prefix}{caption}{self.valves.caption_suffix}"
                            )

                    if captions:
                        content = message.get("content", "")
                        if isinstance(content, str):
                            message["content"] = "\n".join(captions) + "\n\n" + content
                        modified = True

        if modified:
            body["messages"] = messages

        return body
