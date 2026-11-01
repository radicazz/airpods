"""Pure helpers for extracting model references from ComfyUI workflow JSON."""

from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass
from typing import Any

_MODEL_EXTS = (
    ".safetensors",
    ".ckpt",
    ".pt",
    ".pth",
    ".bin",
    ".onnx",
    ".gguf",
)


_INPUT_KEY_TO_FOLDER = {
    "ckpt_name": "checkpoints",
    "checkpoint": "checkpoints",
    "checkpoint_name": "checkpoints",
    "lora_name": "loras",
    "lora": "loras",
    "vae_name": "vae",
    "vae": "vae",
    "clip_name": "clip",
    "clip": "clip",
    "clip_vision": "clip_vision",
    "control_net_name": "controlnet",
    "controlnet_name": "controlnet",
    "controlnet": "controlnet",
    "unet_name": "unet",
    "unet": "unet",
    "upscale_model": "upscale_models",
    "upscale_model_name": "upscale_models",
    "upscaler_name": "upscale_models",
    "embedding": "embeddings",
    "embedding_name": "embeddings",
}


@dataclass(frozen=True)
class ModelRef:
    filename: str
    folder: str | None = None
    subdir: str | None = None
    url: str | None = None
    source: str | None = None


def _coerce_filename(value: str) -> str | None:
    if not isinstance(value, str):
        return None
    name = Path(value).name.strip()
    if not name:
        return None
    if name in {".", ".."}:
        return None
    if any(name.lower().endswith(ext) for ext in _MODEL_EXTS):
        return name
    return None


def _flatten_strings(obj: Any) -> list[str]:
    found: list[str] = []
    if isinstance(obj, str):
        found.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            found.extend(_flatten_strings(v))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(_flatten_strings(v))
    return found


def _extract_model_refs_prompt_format(data: dict) -> list[ModelRef]:
    refs: list[ModelRef] = []
    for node_id, node in data.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for key, value in inputs.items():
            if not isinstance(value, str):
                continue
            filename = _coerce_filename(value)
            if not filename:
                continue
            folder = _INPUT_KEY_TO_FOLDER.get(str(key).lower())
            refs.append(
                ModelRef(
                    filename=filename,
                    folder=folder,
                    subdir=None,
                    source=f"prompt:{node_id}:{key}",
                )
            )
    return refs


def _extract_model_refs_workflow_format(data: dict) -> list[ModelRef]:
    # UI workflow format is not stable across ComfyUI versions. Best-effort:
    # - Prefer per-node metadata if present (models list with directory + url).
    # - Otherwise, map widget values to known model folders when possible.
    # - Finally, scan for strings that look like model filenames anywhere in the document.
    refs: list[ModelRef] = []
    nodes = data.get("nodes")
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_id = node.get("id")
            props = node.get("properties")
            models = props.get("models") if isinstance(props, dict) else None
            if not isinstance(models, list):
                continue
            for model in models:
                if not isinstance(model, dict):
                    continue
                filename = _coerce_filename(str(model.get("name", "")))
                if not filename:
                    continue
                directory = model.get("directory")
                folder = directory.strip() if isinstance(directory, str) else None
                url = model.get("url")
                url_str = url.strip() if isinstance(url, str) and url.strip() else None
                refs.append(
                    ModelRef(
                        filename=filename,
                        folder=folder,
                        subdir=None,
                        url=url_str,
                        source=f"workflow:{node_id}:properties.models",
                    )
                )

        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_id = node.get("id")
            inputs = node.get("inputs")
            widgets_values = node.get("widgets_values")
            if not isinstance(inputs, list) or not isinstance(widgets_values, list):
                continue
            widget_names: list[str] = []
            for inp in inputs:
                if not isinstance(inp, dict):
                    continue
                name = inp.get("name")
                if not isinstance(name, str) or not name.strip():
                    continue
                if not isinstance(inp.get("widget"), dict):
                    continue
                widget_names.append(name.strip())

            for input_name, value in zip(widget_names, widgets_values):
                if not isinstance(value, str):
                    continue
                filename = _coerce_filename(value)
                if not filename:
                    continue
                folder = _INPUT_KEY_TO_FOLDER.get(input_name.lower())
                if not folder:
                    continue
                refs.append(
                    ModelRef(
                        filename=filename,
                        folder=folder,
                        subdir=None,
                        url=None,
                        source=f"workflow:{node_id}:widgets",
                    )
                )

    for s in _flatten_strings(data):
        filename = _coerce_filename(s)
        if filename:
            refs.append(
                ModelRef(
                    filename=filename,
                    folder=None,
                    subdir=None,
                    url=None,
                    source="workflow",
                )
            )
    return refs


def extract_model_refs(workflow: dict) -> list[ModelRef]:
    # Prompt-format: mapping of node-id -> {class_type, inputs}
    if all(isinstance(k, str) for k in workflow.keys()) and any(
        isinstance(v, dict) and "inputs" in v for v in workflow.values()
    ):
        return _extract_model_refs_prompt_format(workflow)

    # Workflow-format: {"nodes":[...], ...}
    if isinstance(workflow.get("nodes"), list):
        return _extract_model_refs_workflow_format(workflow)

    return _extract_model_refs_workflow_format(workflow)


def _dedupe_refs(refs: list[ModelRef]) -> list[ModelRef]:
    grouped: dict[str, list[ModelRef]] = {}
    for ref in refs:
        grouped.setdefault(ref.filename, []).append(ref)

    out: list[ModelRef] = []
    for filename, items in grouped.items():
        # If we have at least one reference that knows the folder, drop
        # folder-less "best-effort" scans for the same filename.
        if any(i.folder for i in items):
            items = [i for i in items if i.folder]

        # When the same filename appears with different folders, prefer the most
        # authoritative reference (one with URL + folder metadata from embedded data).
        # Score each reference: URL=2, folder=1, so URL+folder=3 is best.
        def score_ref(r: ModelRef) -> int:
            s = 0
            if r.url:
                s += 2
            if r.folder:
                s += 1
            return s

        # If all references have folders but point to different destinations,
        # keep only the best one (highest score, breaking ties by keeping first).
        if len(items) > 1 and all(i.folder for i in items):
            folders = {i.folder for i in items}
            if len(folders) > 1:
                # Multiple folders for same file - pick the best reference
                best = max(items, key=lambda r: (score_ref(r), -items.index(r)))
                items = [best]

        by_key: dict[tuple[str, str | None, str | None], ModelRef] = {}
        for ref in items:
            key = (filename, ref.folder, ref.subdir)
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = ref
                continue
            # Prefer entries that carry a URL (so sync can proceed without a mapping file).
            if not existing.url and ref.url:
                by_key[key] = ref
        out.extend(by_key.values())

    return out
