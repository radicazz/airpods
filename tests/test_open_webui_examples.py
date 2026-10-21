from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


PLUGIN_ROOT = Path(__file__).parents[1] / "plugins" / "open-webui"


def _load_plugin(relative_path: str) -> ModuleType:
    path = PLUGIN_ROOT / relative_path
    module_name = f"airpods_test_{path.stem}_{abs(hash(path))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_filter_limits_user_turns_without_requiring_user_context() -> None:
    module = _load_plugin("filters/example_filter.py")
    plugin = module.Filter()
    body = {
        "messages": [
            {"role": "system", "content": "Be helpful"},
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "hello"},
        ]
    }

    assert asyncio.run(plugin.inlet(body)) is body
    plugin.valves.max_turns = 1
    body["messages"].append({"role": "user", "content": "two"})
    with pytest.raises(ValueError, match="2/1 user turns"):
        asyncio.run(plugin.inlet(body))


def test_pipe_returns_latest_structured_user_text_and_status_events() -> None:
    module = _load_plugin("pipes/example_pipeline.py")
    plugin = module.Pipe()
    events: list[dict] = []

    async def emit(event: dict) -> None:
        events.append(event)

    result = asyncio.run(
        plugin.pipe(
            {
                "messages": [
                    {"role": "user", "content": "old"},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "new"},
                            {"type": "image_url", "image_url": {"url": "image"}},
                        ],
                    },
                ]
            },
            __event_emitter__=emit,
        )
    )

    assert result == "Echo: new"
    assert [event["data"]["done"] for event in events] == [False, True]


def test_action_returns_open_webui_message_update_contract() -> None:
    module = _load_plugin("actions/example_action.py")
    result = asyncio.run(
        module.Action().action(
            {
                "id": "assistant-1",
                "messages": [
                    {"id": "user-1", "role": "user", "content": "hello"},
                    {
                        "id": "assistant-1",
                        "role": "assistant",
                        "content": "world",
                    },
                ],
            }
        )
    )

    assert result is not None
    assert result["messages"][0]["id"] == "assistant-1"
    assert "Total messages: 2" in result["messages"][0]["content"]


def test_vision_router_is_async_strips_images_and_caches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_plugin("filters/vision_router.py")
    calls: list[dict] = []

    def fake_post(url: str, payload: dict, timeout_seconds: int) -> dict:
        calls.append({"url": url, "payload": payload, "timeout": timeout_seconds})
        return {"choices": [{"message": {"content": "a small orange cat"}}]}

    monkeypatch.setattr(module, "_http_post_json", fake_post)
    plugin = module.Filter()
    plugin.valves.default_vision_model_id = "vision:latest"

    def request() -> dict:
        return {
            "model": "text:latest",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64,AA=="},
                        },
                    ],
                }
            ],
        }

    first = asyncio.run(plugin.inlet(request()))
    second = asyncio.run(plugin.inlet(request()))

    assert len(calls) == 1
    assert first["messages"][0]["role"] == "system"
    assert "a small orange cat" in first["messages"][0]["content"]
    assert first["messages"][1]["content"] == "Describe this"
    assert second["messages"][1]["content"] == "Describe this"


def test_vision_router_rejects_malformed_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_plugin("filters/vision_router.py")
    monkeypatch.setattr(module, "_http_post_json", lambda *_args: {})
    plugin = module.Filter()
    plugin.valves.default_vision_model_id = "vision"
    body = {
        "model": "text",
        "messages": [
            {
                "role": "user",
                "content": [{"type": "image_url", "image_url": {"url": "image"}}],
            }
        ],
    }

    with pytest.raises(RuntimeError, match="did not include a completion"):
        asyncio.run(plugin.inlet(body))
