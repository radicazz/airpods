"""Workflows command implementation for ComfyUI workflow + model utilities."""

from __future__ import annotations

import json
import difflib
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import typer
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TransferSpeedColumn,
)
from rich.table import Table

from airpods import config as config_module
from airpods import paths
from airpods.logging import console

from ..common import ALIAS_HELP_TEMPLATE, COMMAND_CONTEXT
from ..help import command_help_option, maybe_show_command_help, show_command_help
from ..type_defs import CommandMap

workflows_app = typer.Typer(
    help="ComfyUI workflows and model sync helpers", context_settings=COMMAND_CONTEXT
)


@workflows_app.callback(invoke_without_command=True)
def _workflows_root(
    ctx: typer.Context,
    help_: bool = command_help_option(),
) -> None:
    maybe_show_command_help(ctx, help_)
    if ctx.invoked_subcommand is None:
        show_command_help(ctx)


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


class DownloadError(RuntimeError):
    pass


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


def _comfyui_host_port() -> int:
    spec = config_module.REGISTRY.get("comfyui")
    if spec and spec.ports:
        return spec.ports[0][0]
    return 8188


def _find_comfyui_mount(target_suffix: str) -> Path | None:
    spec = config_module.REGISTRY.get("comfyui")
    if not spec:
        return None
    for vol in spec.volumes:
        if vol.target == target_suffix or vol.target.endswith(target_suffix):
            src = Path(vol.source)
            if src.is_absolute():
                return src
    return None


def _extract_flag_value(args: list[str], flag: str) -> str | None:
    for idx, arg in enumerate(args):
        if arg == flag and idx + 1 < len(args):
            return args[idx + 1]
    return None


def _map_container_path_to_host(container_path: str) -> Path | None:
    spec = config_module.REGISTRY.get("comfyui")
    if not spec:
        return None
    for vol in spec.volumes:
        target = vol.target.rstrip("/")
        if container_path == target or container_path.startswith(f"{target}/"):
            rel = Path(container_path).relative_to(target)
            return Path(vol.source) / rel
    return None


def _comfyui_user_dir_container() -> str | None:
    spec = config_module.REGISTRY.get("comfyui")
    if not spec:
        return None
    if spec.command:
        user_dir = _extract_flag_value(spec.command, "--user-directory")
        if user_dir:
            return user_dir
    # Fall back to provider defaults based on mounts.
    targets = {vol.target for vol in spec.volumes}
    if any(target.startswith("/basedir") for target in targets):
        return "/basedir/user"
    if any(target.startswith("/workspace") for target in targets):
        return "/workspace/user"
    return None


def comfyui_workspace_dir() -> Path:
    path = _find_comfyui_mount("/workspace")
    if path:
        return path
    # Fallback to expected yanwk mount.
    from airpods import state

    return state.resolve_volume_path("comfyui/workspace")


def comfyui_workflows_dir() -> Path:
    """Return the directory where ComfyUI saves user workflow JSON files.

    Depending on the image/provider layout, workflows may live under a "basedir"
    volume (mmartial) or under the ComfyUI folder within the "workspace" volume
    (yanwk). Falls back to the workspace root for backwards compatibility.
    """

    from airpods import state

    preferred: Path | None = None
    user_dir_container = _comfyui_user_dir_container()
    if user_dir_container:
        host_user_dir = _map_container_path_to_host(user_dir_container)
        if host_user_dir:
            preferred = host_user_dir / "default" / "workflows"
            if preferred.exists():
                return preferred

    basedir_root = _find_comfyui_mount("/basedir") or state.resolve_volume_path(
        "comfyui/basedir"
    )
    basedir_candidate = basedir_root / "user" / "default" / "workflows"

    workspace_root = comfyui_workspace_dir()
    workspace_candidate = workspace_root / "ComfyUI" / "user" / "default" / "workflows"

    # Some installs may place user data directly under the workspace root.
    alt_candidate = workspace_root / "user" / "default" / "workflows"

    # Prefer existing layouts first.
    if basedir_candidate.exists():
        return basedir_candidate
    if workspace_candidate.exists():
        return workspace_candidate
    if alt_candidate.exists():
        return alt_candidate
    if preferred is not None and preferred.exists():
        return preferred

    # Fall back to the configured layout, even if it doesn't exist yet.
    spec = config_module.REGISTRY.get("comfyui")
    mount_targets = {vol.target for vol in spec.volumes} if spec else set()
    if "/basedir" in mount_targets:
        return basedir_candidate

    return workspace_candidate


def comfyui_models_dir() -> Path:
    """Return the host-side directory where ComfyUI models are stored.

    Provider-specific paths:
    - yanwk: /root/ComfyUI/models in container
    - mmartial: /basedir/models in container
    """
    spec = config_module.REGISTRY.get("comfyui")
    if not spec:
        raise typer.BadParameter("comfyui service is not enabled in config")

    # Detect provider by checking which volume mounts are present
    mount_targets = {vol.target for vol in spec.volumes}
    is_mmartial = "/basedir" in mount_targets

    if is_mmartial:
        # mmartial: models are at /basedir/models inside the container
        for vol in spec.volumes:
            if vol.target == "/basedir":
                src = Path(vol.source)
                if not src.is_absolute():
                    from airpods import state

                    if vol.source.startswith("bind://"):
                        relative = vol.source[7:]  # strip "bind://"
                        src = state.resolve_volume_path(relative)
                    else:
                        src = state.resolve_volume_path(vol.source)

                models_dir = src / "models"
                models_dir.mkdir(parents=True, exist_ok=True)
                return models_dir
    else:
        # yanwk: models are at /root/ComfyUI/models inside the container
        for vol in spec.volumes:
            if "ComfyUI/models" in vol.target or vol.target.endswith("/models"):
                src = Path(vol.source)
                if not src.is_absolute():
                    from airpods import state

                    if vol.source.startswith("bind://"):
                        relative = vol.source[7:]  # strip "bind://"
                        src = state.resolve_volume_path(relative)
                    else:
                        src = state.resolve_volume_path(vol.source)

                src.mkdir(parents=True, exist_ok=True)
                return src

    raise typer.BadParameter(
        "unable to locate ComfyUI models volume on host; ensure comfyui volumes include a models mount"
    )


def _load_mapping(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        raise typer.BadParameter(f"mapping file not found: {path}")
    if path.suffix.lower() == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
    else:
        import tomlkit

        raw = tomlkit.parse(path.read_text(encoding="utf-8"))

    models = raw.get("models") if isinstance(raw, dict) else None
    if not isinstance(models, dict):
        return {}

    out: dict[str, dict[str, str]] = {}
    for name, value in models.items():
        filename = Path(str(name)).name
        if isinstance(value, str):
            out[filename] = {"url": value}
        elif isinstance(value, dict):
            item: dict[str, str] = {}
            for k in ("url", "folder", "subdir", "filename"):
                v = value.get(k)
                if isinstance(v, str) and v.strip():
                    item[k] = v.strip()
            if "url" in item:
                out[filename] = item
    return out


def _normalize_hf_url(url: str) -> str:
    return re.sub(r"(/)blob(/)", r"\1resolve\2", url)


def _download_to_path(
    url: str,
    dest: Path,
    *,
    hf_token: str | None = None,
    overwrite: bool = False,
    timeout_s: int = 300,
    retries: int = 2,
) -> None:
    if dest.exists() and not overwrite:
        return
    if timeout_s <= 0:
        raise typer.BadParameter("--timeout must be > 0")
    if retries < 0:
        raise typer.BadParameter("--retries must be >= 0")
    dest.parent.mkdir(parents=True, exist_ok=True)

    url = _normalize_hf_url(url)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise typer.BadParameter("only http(s) urls are supported")

    headers = {"User-Agent": "airpods-workflows/0.1"}
    if hf_token:
        headers["Authorization"] = f"Bearer {hf_token}"

    req = Request(url, headers=headers, method="GET")
    tmp = dest.with_suffix(dest.suffix + ".part")

    last_err: str | None = None
    attempts_total = retries + 1
    for attempt in range(1, attempts_total + 1):
        try:
            with urlopen(req, timeout=float(timeout_s)) as resp:
                total = resp.headers.get("Content-Length")
                total_int = int(total) if total and total.isdigit() else None

                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                    DownloadColumn(),
                    TransferSpeedColumn(),
                    TimeElapsedColumn(),
                    console=console,
                ) as progress:
                    task = progress.add_task(
                        f"Downloading {dest.name}", total=total_int or 0
                    )
                    with tmp.open("wb") as f:
                        while True:
                            chunk = resp.read(1024 * 256)
                            if not chunk:
                                break
                            f.write(chunk)
                            progress.update(task, advance=len(chunk))
                    progress.update(
                        task, completed=total_int or progress.tasks[0].completed
                    )

            tmp.replace(dest)
            return
        except HTTPError as exc:
            last_err = f"http {exc.code}: {exc.reason}"
        except URLError as exc:
            last_err = str(getattr(exc, "reason", exc)) or str(exc)
        except TimeoutError as exc:
            last_err = str(exc) or "timed out"
        except OSError as exc:
            last_err = str(exc) or "os error"
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass

        if attempt < attempts_total:
            console.print(
                f"[warn]Download failed (attempt {attempt}/{attempts_total}): {last_err}[/]"
            )
            time.sleep(min(15.0, attempt * 1.5))

    raise DownloadError(last_err or "download failed")


def _list_model_folders(models_root: Path) -> list[str]:
    standard = {
        "checkpoints",
        "loras",
        "vae",
        "clip",
        "clip_vision",
        "controlnet",
        "unet",
        "upscale_models",
        "embeddings",
    }
    found: set[str] = set()
    try:
        for item in models_root.iterdir():
            if item.is_dir():
                found.add(item.name)
    except OSError:
        pass
    return sorted(standard | found)


def _guess_model_folder(filename: str, candidates: set[str]) -> str | None:
    name = filename.lower()
    if "lora" in name and "loras" in candidates:
        return "loras"
    if "vae" in name and "vae" in candidates:
        return "vae"
    if ("controlnet" in name or "control" in name) and "controlnet" in candidates:
        return "controlnet"
    if "clip_vision" in name and "clip_vision" in candidates:
        return "clip_vision"
    if "clip" in name and "clip" in candidates:
        return "clip"
    if "unet" in name and "unet" in candidates:
        return "unet"
    if "upscale" in name and "upscale_models" in candidates:
        return "upscale_models"
    if "checkpoints" in candidates:
        return "checkpoints"
    return None


def _fuzzy_rank(query: str, choices: list[str]) -> list[str]:
    q = query.strip().lower()
    if not q:
        return choices[:]

    scored: list[tuple[int, float, str]] = []
    for c in choices:
        cl = c.lower()
        score = 0
        if cl == q:
            score += 10_000
        if cl.startswith(q):
            score += 2_000
        if q in cl:
            score += 1_000
        ratio = difflib.SequenceMatcher(a=q, b=cl).ratio()
        scored.append((score, ratio, c))

    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [c for _, __, c in scored]


def _interactive_select_folder(filename: str, models_root: Path) -> tuple[str, str]:
    from rich.prompt import Prompt
    from rich.table import Table

    folders = _list_model_folders(models_root)
    folder_set = set(folders)
    guess = _guess_model_folder(filename, folder_set) or folders[0]

    while True:
        query = Prompt.ask(
            f"Folder search for [accent]{filename}[/]", default=guess
        ).strip()
        if query.lower().startswith(("http://", "https://")):
            console.print(
                "[warn]That looks like a URL. You'll be prompted for download URLs separately.[/]"
            )
            query = guess
        ranked = _fuzzy_rank(query, folders)
        shown = ranked[:10]
        if guess not in shown:
            shown = [guess, *[f for f in shown if f != guess]][:10]

        table = Table(show_header=True, show_edge=False, padding=(0, 2))
        table.add_column("#", style="dim", justify="right", width=3)
        table.add_column("Folder", style="cyan", no_wrap=True)
        for idx, folder in enumerate(shown, start=1):
            table.add_row(str(idx), folder)
        console.print(table)

        choice = Prompt.ask(
            "Select folder (number or name, e.g. checkpoints)", default="1"
        ).strip()
        selected: str | None = None
        if choice.isdigit():
            i = int(choice)
            if 1 <= i <= len(shown):
                selected = shown[i - 1]
        else:
            selected = choice

        if selected and selected in folder_set:
            break

        console.print(f"[warn]Invalid folder selection: {choice!r}. Try again.[/]")

    subdir = Prompt.ask("Optional subdirectory (blank for none)", default="").strip()
    if subdir:
        p = Path(subdir)
        if p.is_absolute() or ".." in p.parts:
            raise typer.BadParameter("--subdir must be a relative path without '..'")
        subdir = p.as_posix()
    return selected, subdir


@workflows_app.command(name="path", context_settings=COMMAND_CONTEXT)
def path_cmd(
    ctx: typer.Context,
    help_: bool = command_help_option(),
) -> None:
    """Show host paths for ComfyUI workspace and models volumes."""
    maybe_show_command_help(ctx, help_)
    console.print(f"Workspace:  [accent]{comfyui_workspace_dir()}[/]")
    console.print(f"Workflows:  [accent]{comfyui_workflows_dir()}[/]")
    try:
        console.print(f"Models:     [accent]{comfyui_models_dir()}[/]")
    except typer.BadParameter as exc:
        console.print(f"[warn]{exc}[/]")


@workflows_app.command(name="list", context_settings=COMMAND_CONTEXT)
def list_cmd(
    ctx: typer.Context,
    help_: bool = command_help_option(),
    limit: int = typer.Option(50, "--limit", help="Maximum workflows to show."),
) -> None:
    """List saved workflow JSON files with model info."""
    maybe_show_command_help(ctx, help_)
    root = comfyui_workflows_dir()
    if not root.exists():
        console.print(f"[warn]Workflows directory not found: {root}[/]")
        raise typer.Exit(1)

    workflows: list[Path] = sorted(root.rglob("*.json"))
    if not workflows:
        console.print(f"[info]No workflow JSON files found in: {root}[/]")
        return

    shown = workflows[: max(1, limit)]

    # Try to get models directory for checking sync status
    try:
        models_root = comfyui_models_dir()
    except typer.BadParameter:
        # If we can't access models dir, just show basic list
        for path in shown:
            rel = path.relative_to(root)
            console.print(f"- [accent]{rel}[/]")
        if len(workflows) > len(shown):
            console.print(f"[dim]…and {len(workflows) - len(shown)} more[/dim]")
        return

    # Build table with workflow info
    from rich.table import Table

    table = Table(show_header=True, show_edge=False, show_lines=False, padding=(0, 2))
    table.add_column("Workflow", style="cyan", no_wrap=False)
    table.add_column("Models", justify="right", style="yellow")
    table.add_column("Auto-sync", justify="center", style="magenta")
    table.add_column("Status", style="green")

    for path in shown:
        rel = path.relative_to(root)
        # Display name without .json extension
        display_name = str(rel)
        if display_name.lower().endswith(".json"):
            display_name = display_name[:-5]

        # Try to load and analyze the workflow
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            refs = _dedupe_refs(extract_model_refs(data))

            if not refs:
                # No models found
                table.add_row(display_name, "0", "[dim]—[/]", "[dim]—[/]")
                continue

            # Check how many models are missing
            missing_count = 0
            missing_refs: list[ModelRef] = []
            for ref in refs:
                filename = ref.filename
                if ref.folder:
                    # Check in the specific folder
                    subdir = ref.subdir or ""
                    candidate = models_root / ref.folder / subdir / filename
                    if not candidate.exists():
                        missing_count += 1
                        missing_refs.append(ref)
                else:
                    # Check anywhere in models directory
                    found = next(models_root.rglob(filename), None)
                    if found is None:
                        missing_count += 1
                        missing_refs.append(ref)

            total = len(refs)
            synced = total - missing_count

            mapping_dict: dict[str, dict[str, str]] = {}
            mapping_path = path.with_suffix(".toml")
            if mapping_path.exists():
                try:
                    mapping_dict = _load_mapping(mapping_path)
                except typer.BadParameter:
                    mapping_dict = {}

            def _has_sync_info(ref: ModelRef) -> bool:
                entry = mapping_dict.get(ref.filename) if mapping_dict else None
                url = (entry or {}).get("url") or ref.url
                folder = (entry or {}).get("folder") or ref.folder
                return bool(url) and bool(folder)

            can_auto_sync = missing_count == 0 or all(
                _has_sync_info(ref) for ref in missing_refs
            )
            auto_sync = "[ok]✓[/]" if can_auto_sync else "[error]✗[/]"

            # Format status
            if missing_count == 0:
                status = "[ok]✓ synced[/]"
            elif missing_count < total / 2:
                status = f"[warn]⚠ {missing_count} missing[/]"
            else:
                status = f"[error]✗ {missing_count} missing[/]"

            table.add_row(display_name, str(total), auto_sync, status)

        except Exception as e:
            # If we can't parse the workflow, show basic info
            table.add_row(display_name, "?", "[dim]?[/]", f"[dim]error: {e}[/]")

    console.print(table)

    if len(workflows) > len(shown):
        console.print(
            f"[dim]…and {len(workflows) - len(shown)} more (use --limit to show more)[/dim]"
        )


@workflows_app.command(name="api", context_settings=COMMAND_CONTEXT)
def api_cmd(
    ctx: typer.Context,
    help_: bool = command_help_option(),
) -> None:
    """Show ComfyUI API endpoints and URLs."""
    maybe_show_command_help(ctx, help_)
    port = _comfyui_host_port()
    base = f"http://localhost:{port}"
    console.print(f"UI:  [accent]{base}[/]")
    console.print(f"API: [accent]{base}[/]")
    console.print("[dim]Common endpoints:[/dim]")
    console.print(f"  [dim]• POST {base}/prompt[/dim]")
    console.print(f"  [dim]• GET  {base}/queue[/dim]")
    console.print(f"  [dim]• GET  {base}/history[/dim]")
    console.print(f"  [dim]• GET  {base}/system_stats[/dim]")


def _resolve_workflow_path(workflow: str) -> Path:
    p = Path(workflow)
    if p.exists():
        return p

    # Allow passing a path relative to the workflows dir or workspace, or a basename.
    workflows_root = comfyui_workflows_dir()
    workspace_root = comfyui_workspace_dir()
    for base in (workflows_root, workspace_root):
        candidate = base / workflow
        if candidate.exists():
            return candidate
        if not workflow.lower().endswith(".json"):
            candidate2 = base / f"{workflow}.json"
            if candidate2.exists():
                return candidate2
    raise typer.BadParameter(f"workflow not found: {workflow}")


def _resolve_workflow_path_restricted(workflow: str) -> Path:
    """Resolve a workflow path, restricting deletion to ComfyUI volumes."""
    workflows_root = comfyui_workflows_dir().resolve()
    workspace_root = comfyui_workspace_dir().resolve()

    p = Path(workflow)
    if p.exists():
        resolved = p.resolve()
        allowed = resolved.is_relative_to(workflows_root) or resolved.is_relative_to(
            workspace_root
        )
        if not allowed:
            raise typer.BadParameter(
                "workflow is outside ComfyUI workspace/workflows directories; "
                "pass a workspace-relative name or move the file into the workflows volume"
            )
        return resolved

    for base in (workflows_root, workspace_root):
        candidate = (base / workflow).resolve()
        if candidate.exists():
            return candidate
        if not workflow.lower().endswith(".json"):
            candidate2 = (base / f"{workflow}.json").resolve()
            if candidate2.exists():
                return candidate2

    raise typer.BadParameter(f"workflow not found: {workflow}")


def _discover_repo_workflows() -> list[Path]:
    """Find bundled workflow JSON files (repo checkout or installed package)."""
    candidates: list[Path] = []

    repo_root = paths.detect_repo_root()
    if repo_root:
        candidates.append(repo_root / "plugins" / "comfyui" / "workflows")

    module_path = Path(__file__).resolve()
    # Look for a packaged plugins/ directory near the installed module location.
    for parent in module_path.parents[:6]:
        candidates.append(parent / "plugins" / "comfyui" / "workflows")

    seen: set[Path] = set()
    for workflows_dir in candidates:
        try:
            resolved = workflows_dir.resolve()
        except OSError:
            resolved = workflows_dir
        if resolved in seen:
            continue
        seen.add(resolved)

        if not workflows_dir.exists():
            continue
        workflows = sorted(workflows_dir.glob("*.json"))
        if workflows:
            return workflows

    return []


@workflows_app.command(name="add", context_settings=COMMAND_CONTEXT)
def add_cmd(
    ctx: typer.Context,
    help_: bool = command_help_option(),
    source: Optional[str] = typer.Argument(
        None, help="Workflow source: file path, URL, or repo workflow name."
    ),
    overwrite: bool = typer.Option(
        False, "--overwrite", help="Overwrite existing workflow if present."
    ),
    sync: bool = typer.Option(
        False, "--sync", help="Run sync after importing to download models."
    ),
) -> None:
    """Import workflow JSON files from local paths, URLs, or repo workflows.

    If no source is provided, displays bundled workflows from plugins/comfyui/workflows
    when present (forks can add their own). Otherwise, use a local file path or URL.

    Examples:
        airpods workflows add my-workflow
        airpods workflows add /path/to/workflow.json
        airpods workflows add https://example.com/workflow.json
        airpods workflows add my-workflow --sync
    """
    maybe_show_command_help(ctx, help_)

    workflows_dir = comfyui_workflows_dir()
    workflows_dir.mkdir(parents=True, exist_ok=True)

    # No source: list available workflows from repo
    if not source:
        repo_workflows = _discover_repo_workflows()
        if not repo_workflows:
            console.print(
                "[warn]No bundled workflows found in plugins/comfyui/workflows/.[/]"
            )
            console.print(
                "[info]Use a local file path or URL, or add workflows in your fork.[/]"
            )
            return
        console.print(
            f"[info]Bundled workflows located at {repo_workflows[0].parent}[/]"
        )

        table = Table(show_header=True, show_edge=False, padding=(0, 2))
        table.add_column("#", style="dim", justify="right", width=3)
        table.add_column("Workflow", style="cyan")
        table.add_column("Size", style="yellow", justify="right")

        for idx, wf_path in enumerate(repo_workflows, start=1):
            size = wf_path.stat().st_size
            size_str = _format_bytes(size)
            # Display without .json extension
            display_name = wf_path.stem
            table.add_row(str(idx), display_name, size_str)

        console.print(table)
        console.print(
            f"\n[info]Found {len(repo_workflows)} workflow(s). "
            "Use [accent]airpods workflows add <name>[/] to import.[/]"
        )
        return

    # Detect source type
    source_path = Path(source)
    is_url = source.startswith(("http://", "https://"))

    # Local file path
    if source_path.exists() and source_path.is_file():
        if not source.lower().endswith(".json"):
            raise typer.BadParameter("workflow must be a .json file")

        # Copy JSON file
        dest_name = source_path.name
        dest = workflows_dir / dest_name
        if dest.exists() and not overwrite:
            raise typer.BadParameter(
                f"workflow {dest_name} already exists (use --overwrite to replace)"
            )

        shutil.copy2(source_path, dest)
        console.print(f"[ok]✓ Imported: {dest_name} -> {dest}[/]")

        # Check for companion TOML file
        toml_file = source_path.with_suffix(".toml")
        if toml_file.exists():
            toml_dest = dest.with_suffix(".toml")
            shutil.copy2(toml_file, toml_dest)
            console.print(f"[ok]✓ Imported mapping: {toml_file.name}[/]")

        # Run sync if requested
        if sync:
            console.print(f"[info]Running sync for {dest_name}...[/]")
            ctx.invoke(sync_cmd, workflow=str(dest), yes=True)

        return

    # URL download
    if is_url:
        # Infer filename from URL
        parsed = urlparse(source)
        filename = Path(parsed.path).name
        if not filename or not filename.lower().endswith(".json"):
            filename = "workflow.json"

        dest = workflows_dir / filename
        if dest.exists() and not overwrite:
            raise typer.BadParameter(
                f"workflow {filename} already exists (use --overwrite to replace)"
            )

        console.print(f"[info]Downloading {source}...[/]")
        try:
            _download_to_path(
                source, dest, overwrite=overwrite, timeout_s=60, retries=2
            )
            console.print(f"[ok]✓ Imported: {filename} -> {dest}[/]")
        except DownloadError as exc:
            console.print(f"[error]✗ Download failed: {exc}[/]")
            raise typer.Exit(1)

        # Run sync if requested
        if sync:
            console.print(f"[info]Running sync for {filename}...[/]")
            ctx.invoke(sync_cmd, workflow=str(dest), yes=True)

        return

    # Repo workflow name
    repo_workflows = _discover_repo_workflows()
    if not repo_workflows:
        raise typer.BadParameter(
            "no bundled workflows found in plugins/comfyui/workflows; "
            "use a local file path/URL or add workflows in your fork"
        )
    console.print(f"[info]Bundled workflows located at {repo_workflows[0].parent}[/]")

    # Search for workflow by name (with or without .json)
    search_name = source if source.lower().endswith(".json") else f"{source}.json"
    matched = None
    for wf_path in repo_workflows:
        if wf_path.name.lower() == search_name.lower():
            matched = wf_path
            break

    if not matched:
        available = ", ".join(wf.stem for wf in repo_workflows[:5])
        raise typer.BadParameter(
            f"workflow '{source}' not found in repo. Available: {available}"
        )

    # Copy JSON file
    dest_name = matched.name
    dest = workflows_dir / dest_name
    if dest.exists() and not overwrite:
        raise typer.BadParameter(
            f"workflow {dest_name} already exists (use --overwrite to replace)"
        )

    shutil.copy2(matched, dest)
    console.print(f"[ok]✓ Imported: {dest_name} -> {dest}[/]")

    # Check for companion TOML file
    toml_file = matched.with_suffix(".toml")
    toml_dest: Path | None = None
    if toml_file.exists():
        toml_dest = dest.with_suffix(".toml")
        shutil.copy2(toml_file, toml_dest)
        console.print(f"[ok]✓ Imported mapping: {toml_file.name}[/]")

    # Run sync if requested
    if sync:
        console.print(f"[info]Running sync for {dest_name}...[/]")
        mapping_arg = toml_dest if toml_dest is not None else None
        ctx.invoke(sync_cmd, workflow=str(dest), mapping=mapping_arg, yes=True)


@workflows_app.command(name="sync", context_settings=COMMAND_CONTEXT)
def sync_cmd(
    ctx: typer.Context,
    help_: bool = command_help_option(),
    workflow: Optional[str] = typer.Argument(
        None, help="Workflow JSON file (path or workspace-relative)."
    ),
    mapping: Optional[Path] = typer.Option(
        None,
        "--map",
        help="TOML/JSON mapping of filenames to HuggingFace URLs (and optional folder/subdir).",
    ),
    hf_token: Optional[str] = typer.Option(
        None,
        "--hf-token",
        envvar="HF_TOKEN",
        help="HuggingFace token (optional; needed for gated models).",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Download without prompting."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be downloaded without downloading."
    ),
    overwrite: bool = typer.Option(
        False, "--overwrite", help="Overwrite existing files if present."
    ),
    interactive: bool | None = typer.Option(
        None,
        "--interactive/--no-interactive",
        help="Interactively resolve missing model folders/URLs when metadata is absent.",
    ),
    timeout_s: int = typer.Option(
        300, "--timeout", help="Network read timeout in seconds for downloads."
    ),
    retries: int = typer.Option(2, "--retries", help="Retry count for downloads."),
) -> None:
    """Install missing models for a workflow.

    Uses an optional local URL mapping file, and also supports workflow-embedded
    model metadata (directory + download URL) when present.
    When no workflow is provided, lists available workflows.
    """
    maybe_show_command_help(ctx, help_)
    if not workflow:
        ctx.invoke(list_cmd)
        return

    workflow_path = _resolve_workflow_path(workflow)
    data = json.loads(workflow_path.read_text(encoding="utf-8"))
    refs = _dedupe_refs(extract_model_refs(data))
    if not refs:
        console.print("[info]No model-like references found in workflow[/]")
        return

    models_root = comfyui_models_dir()
    if mapping is None:
        auto_mapping = workflow_path.with_suffix(".toml")
        if auto_mapping.exists():
            mapping = auto_mapping
            console.print(f"[info]Using mapping: {auto_mapping.name}[/]")

    mapping_dict = _load_mapping(mapping) if mapping else {}

    missing: list[tuple[ModelRef, Path, str | None, str]] = []
    for ref in refs:
        entry = mapping_dict.get(ref.filename)
        folder = (entry or {}).get("folder") or ref.folder
        subdir = (entry or {}).get("subdir") or ref.subdir or ""
        filename = (entry or {}).get("filename") or ref.filename
        url = (entry or {}).get("url") or ref.url or ""

        if folder:
            candidate = models_root / folder / subdir / filename
            if candidate.exists():
                continue
            missing.append((ref, candidate, folder, url))
        else:
            # Unknown folder: treat as missing if not found anywhere under models_root.
            found = next(models_root.rglob(ref.filename), None)
            if found is None:
                missing.append((ref, models_root / ref.filename, None, url))

    if not missing:
        console.print("[ok]✓ No missing models detected[/]")
        return

    # Separate models with URLs from those without
    with_urls = [(ref, dest, folder, url) for ref, dest, folder, url in missing if url]
    without_urls = [
        (ref, dest, folder, url) for ref, dest, folder, url in missing if not url
    ]

    console.print(f"[warn]Missing models: {len(missing)}[/]")

    # Show models that can be synced
    if with_urls:
        console.print(f"[ok]Models with URLs (can sync): {len(with_urls)}[/]")
        for ref, dest, folder, url in with_urls:
            folder_disp = folder or "?"
            console.print(
                f"  [accent]{ref.filename}[/] → models/{folder_disp} "
                f"[dim](from {ref.source or 'workflow'})[/dim]"
            )

    # Show models that need mapping
    if without_urls:
        console.print(f"[warn]Models without URLs (need --map): {len(without_urls)}[/]")
        for ref, dest, folder, url in without_urls:
            folder_disp = folder or "?"
            console.print(f"  [dim]{ref.filename} → models/{folder_disp}[/]")

    do_interactive = (
        interactive if interactive is not None else (not dry_run and not yes)
    )
    if not with_urls and without_urls and do_interactive:
        from rich.prompt import Confirm, Prompt

        console.print(
            "[info]No download URLs found. I can help you assign destination folders now.[/]"
        )
        prompt_urls = False
        if not dry_run:
            prompt_urls = Confirm.ask(
                "Do you want to enter download URLs now?", default=False
            )

        enriched: dict[str, dict[str, str]] = {}
        new_with_urls: list[tuple[ModelRef, Path, str | None, str]] = []
        new_without_urls: list[tuple[ModelRef, Path, str | None, str]] = []

        for ref, dest, folder, url in without_urls:
            entered_url = ""
            if prompt_urls:
                entered_url = Prompt.ask(
                    f"URL for [accent]{ref.filename}[/] (blank to skip)", default=""
                ).strip()

            selected_folder = folder
            subdir = ""
            if not selected_folder:
                selected_folder, subdir = _interactive_select_folder(
                    ref.filename, models_root
                )

            entry: dict[str, str] = {}
            if selected_folder:
                entry["folder"] = selected_folder
            if subdir:
                entry["subdir"] = subdir
            if entered_url:
                entry["url"] = entered_url
            enriched[ref.filename] = entry

            new_dest = (
                models_root / selected_folder / subdir / ref.filename
                if selected_folder
                else dest
            )
            if entered_url:
                new_with_urls.append((ref, new_dest, selected_folder, entered_url))
            else:
                new_without_urls.append((ref, new_dest, selected_folder, ""))

        if enriched:
            console.print(
                "[dim]Mapping template (add URLs and re-run with --map):[/dim]"
            )
            console.print(
                json.dumps({"models": enriched}, indent=2, sort_keys=True),
            )

        with_urls = new_with_urls
        without_urls = new_without_urls

    # If there are no models to sync, exit early
    if not with_urls:
        if dry_run:
            console.print(
                f"[warn]All {len(missing)} missing model(s) lack URL metadata. "
                "Add them to --map (or re-run without --dry-run and use --interactive).[/]"
            )
            return
        console.print(
            f"[warn]No models can be downloaded without URLs. "
            "Add them to --map and re-run.[/]"
        )
        return

    # If there are models without URLs, warn but continue with available ones
    if without_urls:
        console.print(
            f"[info]Will sync {len(with_urls)} model(s) with URLs. "
            f"{len(without_urls)} model(s) will be skipped (add to --map to include).[/]"
        )

    if dry_run:
        return

    if not yes:
        from rich.prompt import Confirm

        if not Confirm.ask(f"Download {len(with_urls)} model(s) now?"):
            raise typer.Exit(0)

    failures: list[tuple[str, str]] = []
    for ref, dest, folder, url in with_urls:
        if not folder:
            console.print(f"[warn]Skipping {ref.filename}: unknown folder[/]")
            continue
        console.print(f"[info]→ {ref.filename}[/]")
        try:
            _download_to_path(
                url,
                dest,
                hf_token=hf_token,
                overwrite=overwrite,
                timeout_s=timeout_s,
                retries=retries,
            )
        except DownloadError as exc:
            failures.append((ref.filename, str(exc)))
            console.print(f"[error]✗ {ref.filename}: {exc}[/]")

    if failures:
        console.print(f"[error]{len(failures)} download(s) failed[/]")
        raise typer.Exit(1)

    synced = len(with_urls) - len(failures)
    if synced > 0:
        console.print(f"[ok]✓ Synced {synced} model(s)[/]")

    if without_urls:
        console.print(f"[warn]{len(without_urls)} model(s) still need URLs to sync[/]")


def _format_bytes(bytes_count: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_count < 1024.0:
            return f"{bytes_count:.1f}{unit}"
        bytes_count /= 1024.0
    return f"{bytes_count:.1f}TB"


def _prune_empty_dirs(path: Path, *, stop_at: Path) -> None:
    try:
        stop_at_resolved = stop_at.resolve()
        current = path.resolve()
    except OSError:
        return

    if current == stop_at_resolved:
        return

    while True:
        if current == stop_at_resolved:
            return
        if not current.is_dir():
            return
        try:
            next(current.iterdir())
            return
        except StopIteration:
            pass
        except OSError:
            return

        try:
            current.rmdir()
        except OSError:
            return

        current = current.parent


@workflows_app.command(name="desync", context_settings=COMMAND_CONTEXT)
def desync_cmd(
    ctx: typer.Context,
    help_: bool = command_help_option(),
    workflow: str = typer.Argument(
        ..., help="Workflow JSON file (path or workspace-relative)."
    ),
    mapping: Optional[Path] = typer.Option(
        None,
        "--map",
        help="TOML/JSON mapping of filenames to folders/subdirs (and optional URLs).",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Delete without prompting."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be deleted without deleting."
    ),
    unsafe_search: bool = typer.Option(
        False,
        "--unsafe-search",
        help="For models without folder metadata, search by filename under models/ and delete if a single match is found.",
    ),
) -> None:
    """Delete local model files referenced by a workflow to reclaim disk space.

    Warning: this may remove models used by other workflows.
    """
    maybe_show_command_help(ctx, help_)

    workflow_path = _resolve_workflow_path(workflow)
    data = json.loads(workflow_path.read_text(encoding="utf-8"))
    refs = _dedupe_refs(extract_model_refs(data))
    if not refs:
        console.print("[info]No model-like references found in workflow[/]")
        return

    models_root = comfyui_models_dir()
    mapping_dict = _load_mapping(mapping) if mapping else {}

    targets: dict[Path, str] = {}
    skipped_unknown: list[str] = []

    for ref in refs:
        entry = mapping_dict.get(ref.filename)
        folder = (entry or {}).get("folder") or ref.folder
        subdir = (entry or {}).get("subdir") or ref.subdir or ""
        filename = (entry or {}).get("filename") or ref.filename

        if folder:
            candidate = models_root / folder / subdir / filename
            if candidate.exists() and candidate.is_file():
                try:
                    targets[candidate.resolve()] = ref.filename
                except OSError:
                    targets[candidate] = ref.filename
            continue

        if not unsafe_search:
            skipped_unknown.append(ref.filename)
            continue

        matches = [p for p in models_root.rglob(ref.filename) if p.is_file()]
        if len(matches) == 1:
            try:
                targets[matches[0].resolve()] = ref.filename
            except OSError:
                targets[matches[0]] = ref.filename
        else:
            skipped_unknown.append(ref.filename)

    if not targets:
        console.print("[info]No matching local model files found to delete[/]")
        if skipped_unknown:
            console.print(
                f"[dim]Skipped {len(skipped_unknown)} model(s) without folder metadata "
                "(pass --unsafe-search to try filename matching).[/dim]"
            )
        return

    total_bytes = 0
    for p in targets:
        try:
            total_bytes += p.stat().st_size
        except OSError:
            pass

    console.print(
        f"[warn]Will delete {len(targets)} file(s) (~{_format_bytes(total_bytes)}) from models/[/]"
    )
    for p in sorted(targets):
        try:
            rel = p.relative_to(models_root)
            console.print(f"  [dim]- models/{rel.as_posix()}[/dim]")
        except ValueError:
            console.print(f"  [dim]- {p}[/dim]")

    if skipped_unknown:
        console.print(
            f"[dim]Skipped {len(skipped_unknown)} model(s) without a safe destination.[/dim]"
        )

    if dry_run:
        return

    if not yes:
        from rich.prompt import Confirm

        if not Confirm.ask(
            f"Delete {len(targets)} file(s) referenced by this workflow?",
            default=False,
        ):
            raise typer.Exit(0)

    deleted = 0
    deleted_bytes = 0
    for p in sorted(targets):
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        try:
            p.unlink()
        except OSError as exc:
            console.print(f"[warn]Failed to delete {p}: {exc}[/]")
            continue
        deleted += 1
        deleted_bytes += size
        _prune_empty_dirs(p.parent, stop_at=models_root)

    console.print(
        f"[ok]✓ Deleted {deleted} file(s) (freed ~{_format_bytes(deleted_bytes)})[/]"
    )


@workflows_app.command(name="remove", context_settings=COMMAND_CONTEXT)
def remove_cmd(
    ctx: typer.Context,
    help_: bool = command_help_option(),
    workflow: str = typer.Argument(
        ..., help="Workflow JSON file (path or workspace-relative)."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Delete without prompting."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be deleted without deleting."
    ),
) -> None:
    """Remove a saved workflow JSON file."""
    maybe_show_command_help(ctx, help_)
    workflow_path = _resolve_workflow_path_restricted(workflow)
    if workflow_path.suffix.lower() != ".json":
        raise typer.BadParameter("workflow must be a .json file")
    if not workflow_path.is_file():
        raise typer.BadParameter(f"workflow is not a file: {workflow_path}")

    display_root = comfyui_workflows_dir()
    try:
        display = str(workflow_path.relative_to(display_root))
    except ValueError:
        display = str(workflow_path)

    if dry_run:
        console.print(f"[info]Would remove: [accent]{display}[/]")
        return

    if not yes:
        from rich.prompt import Confirm

        if not Confirm.ask(f"Remove workflow [accent]{display}[/]?"):
            raise typer.Exit(0)

    workflow_path.unlink()
    console.print(f"[ok]✓ Removed: {display}[/]")


@workflows_app.command(name="pull", context_settings=COMMAND_CONTEXT)
def pull_cmd(
    ctx: typer.Context,
    help_: bool = command_help_option(),
    url: str = typer.Argument(..., help="Direct model file URL (HF recommended)."),
    folder: str = typer.Option(
        ...,
        "--folder",
        "-f",
        help="ComfyUI models subfolder (e.g. checkpoints, loras).",
    ),
    filename: Optional[str] = typer.Option(
        None, "--name", "-n", help="Filename to save as (defaults to URL basename)."
    ),
    subdir: str = typer.Option(
        "", "--subdir", help="Optional subdirectory under folder."
    ),
    hf_token: Optional[str] = typer.Option(
        None,
        "--hf-token",
        envvar="HF_TOKEN",
        help="HuggingFace token (optional; needed for gated models).",
    ),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite if exists."),
    timeout_s: int = typer.Option(
        300, "--timeout", help="Network read timeout in seconds for downloads."
    ),
    retries: int = typer.Option(2, "--retries", help="Retry count for downloads."),
) -> None:
    """Download a single model file into the ComfyUI models directory."""
    maybe_show_command_help(ctx, help_)
    models_root = comfyui_models_dir()
    name = filename or Path(urlparse(url).path).name
    if not name:
        raise typer.BadParameter("unable to infer filename from URL; pass --name")
    dest = models_root / folder / subdir / Path(name).name
    console.print(f"[info]Saving to: [accent]{dest}[/]")
    try:
        _download_to_path(
            url,
            dest,
            hf_token=hf_token,
            overwrite=overwrite,
            timeout_s=timeout_s,
            retries=retries,
        )
    except DownloadError as exc:
        console.print(f"[error]✗ Download failed: {exc}[/]")
        raise typer.Exit(1)
    console.print("[ok]✓ Download complete[/]")


def register(app: typer.Typer) -> CommandMap:
    app.add_typer(workflows_app, name="workflows")

    # Register hidden aliases for subcommands (e.g. ls for list, delete for remove).
    # Keeps help tables clean (alias appears inline in purple next to canonical)
    # and ensures `airpods workflows delete` and `ls` work as documented.
    workflows_app.command(
        name="ls",
        help=ALIAS_HELP_TEMPLATE.format(canonical="list"),
        hidden=True,
        context_settings=COMMAND_CONTEXT,
    )(list_cmd)

    workflows_app.command(
        name="delete",
        help=ALIAS_HELP_TEMPLATE.format(canonical="remove"),
        hidden=True,
        context_settings=COMMAND_CONTEXT,
    )(remove_cmd)

    return {}
