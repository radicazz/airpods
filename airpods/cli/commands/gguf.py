"""Standalone GGUF file management and HuggingFace search commands."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Optional

import typer

from airpods import gguf, ollama, ui
from airpods.logging import console

from ..common import ALIAS_HELP_TEMPLATE, COMMAND_CONTEXT, get_cli_config
from ..help import command_help_option, maybe_show_command_help, show_command_help
from ..type_defs import CommandMap

gguf_app = typer.Typer(help="Manage GGUF model files", context_settings=COMMAND_CONTEXT)


@gguf_app.callback(invoke_without_command=True)
def _gguf_root(
    ctx: typer.Context,
    help_: bool = command_help_option(),
) -> None:
    """Entry point for the gguf command group."""
    maybe_show_command_help(ctx, help_)
    if ctx.invoked_subcommand is None:
        show_command_help(ctx)


def _gguf_dir() -> Path:
    return gguf.gguf_models_dir()


def _format_mtime(epoch_seconds: float) -> str:
    now = time.time()
    delta = max(0, now - epoch_seconds)
    if delta < 60:
        return f"{int(delta)}s"
    if delta < 3600:
        return f"{int(delta // 60)}m"
    if delta < 86400:
        return f"{int(delta // 3600)}h"
    return f"{int(delta // 86400)}d"


@gguf_app.command(name="list", context_settings=COMMAND_CONTEXT)
def list_gguf_cmd(
    ctx: typer.Context,
    help_: bool = command_help_option(),
) -> None:
    """List GGUF models in the local GGUF store."""

    maybe_show_command_help(ctx, help_)
    path = _gguf_dir()

    if not path.exists():
        console.print("[info]No GGUF models directory found[/]")
        return

    models = sorted(path.glob("*.gguf"))
    if not models:
        console.print("[info]No GGUF models found[/]")
        return

    table = ui.themed_table()
    table.add_column("Model", no_wrap=True)
    table.add_column("Size", justify="right")
    table.add_column("Modified")

    for model in models:
        size = ollama.format_size(model.stat().st_size)
        mtime = model.stat().st_mtime
        modified = _format_mtime(mtime)
        table.add_row(model.name, size, modified)

    console.print(table)


def _choose(label: str, options: list[str], default: int = 1) -> int:
    """Prompt for a 1-based choice from ``options``; returns the 0-based index."""
    for i, text in enumerate(options, 1):
        console.print(f"  {i}. {text}")
    while True:
        pick = typer.prompt(f"{label} [1-{len(options)}]", type=int, default=default)
        if 1 <= pick <= len(options):
            return pick - 1
        console.print(f"[error]Invalid selection. Please choose 1-{len(options)}[/]")


def _describe(group: list[dict]) -> str:
    total = sum(f["size"] for f in group)
    suffix = f", {len(group)} shards" if len(group) > 1 else ""
    return f"{group[0]['filename']} ({ollama.format_size(total)}{suffix})"


def _pull_gguf_from_hf(
    repo: str,
    quant: Optional[str],
    *,
    name: Optional[str],
    mmproj: Optional[bool],
    yes: bool,
    hf_token: Optional[str],
) -> None:
    """Download a GGUF (and optional mmproj) from HuggingFace, llama.cpp -hf style."""
    try:
        console.print(f"Fetching GGUF files from [accent]{repo}[/]...")
        files = ollama.list_gguf_files(repo, hf_token=hf_token)
    except ollama.OllamaAPIError as exc:
        console.print(f"[error]{exc}[/]")
        raise typer.Exit(1)

    groups = sorted(gguf.group_model_files(files), key=lambda g: g[0]["filename"])
    if not groups:
        console.print(f"[error]No model GGUF files found in '{repo}'[/]")
        raise typer.Exit(1)

    wanted = quant or gguf.DEFAULT_QUANT
    matches = gguf.match_quant(groups, wanted)
    if len(matches) == 1:
        chosen = matches[0]
    else:
        if not matches:
            level = "error" if quant else "warn"
            console.print(f"[{level}]No file matches quant '{wanted}' in {repo}.[/]")
            if quant:
                raise typer.Exit(1)
        else:
            console.print(f"Multiple files match '{wanted}':")
        if yes:
            console.print("[error]Ambiguous selection; rerun without --yes.[/]")
            raise typer.Exit(1)
        options = matches or groups
        chosen = options[_choose("Select file", [_describe(g) for g in options])]

    extra: list[dict] = []
    projectors = gguf.mmproj_files(files)
    if projectors and mmproj is not False:
        if mmproj is None and not yes:
            console.print("\nThis repo has multimodal projector (mmproj) file(s).")
            if ui.confirm_action("Also download an mmproj file?", default=True):
                mmproj = True
        if mmproj:
            if len(projectors) == 1:
                extra = projectors
            else:
                if yes:
                    console.print(
                        "[error]Multiple mmproj files; rerun without --yes "
                        "to select one.[/]"
                    )
                    raise typer.Exit(1)
                preferred = next(
                    (
                        i
                        for i, f in enumerate(projectors, 1)
                        if "f16" in f["filename"].lower()
                    ),
                    1,
                )
                opts = [
                    f"{f['filename']} ({ollama.format_size(f['size'])})"
                    for f in projectors
                ]
                extra = [projectors[_choose("Select mmproj", opts, preferred)]]

    if name and (len(chosen) > 1 or extra):
        console.print(
            "[error]--name only applies to a single file; "
            "it cannot be used with split shards or mmproj.[/]"
        )
        raise typer.Exit(1)

    try:
        for entry in [*chosen, *extra]:
            dest, size_bytes = gguf.download_hf_file(
                repo,
                entry["filename"],
                name=name if entry in chosen else None,
                hf_token=hf_token,
            )
            console.print(
                f"[ok]Saved GGUF model: {dest} ({ollama.format_size(size_bytes)})[/]"
            )
    except FileExistsError as exc:
        console.print(f"[warn]{exc}[/]")
        raise typer.Exit(code=1)
    except Exception as exc:
        console.print(f"[error]Failed to download GGUF model: {exc}[/]")
        raise typer.Exit(code=1)


@gguf_app.command(name="pull", context_settings=COMMAND_CONTEXT)
def pull_gguf_cmd(
    ctx: typer.Context,
    help_: bool = command_help_option(),
    url: str = typer.Argument(
        ...,
        help="Direct URL to a GGUF file, or a HuggingFace spec like owner/repo[:QUANT].",
    ),
    name: Optional[str] = typer.Option(
        None, "--name", "-n", help="Override the filename to save as."
    ),
    mmproj: Optional[bool] = typer.Option(
        None,
        "--mmproj/--no-mmproj",
        help="HuggingFace specs: also download (or skip) the mmproj file; prompts if unset.",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip prompts (mmproj is skipped unless --mmproj)."
    ),
    hf_token: Optional[str] = typer.Option(
        None, "--hf-token", envvar="HF_TOKEN", help="HuggingFace token for gated repos."
    ),
) -> None:
    """Download a GGUF file into the local GGUF store."""

    maybe_show_command_help(ctx, help_)
    hf_spec = gguf.parse_hf_spec(url)
    if hf_spec:
        yes = yes or get_cli_config().auto_confirm
        _pull_gguf_from_hf(
            hf_spec[0], hf_spec[1], name=name, mmproj=mmproj, yes=yes, hf_token=hf_token
        )
        return
    try:
        dest, size_bytes = gguf.download_model(url, name=name)
    except FileExistsError as exc:
        console.print(f"[warn]{exc}[/]")
        raise typer.Exit(code=1)
    except Exception as exc:
        console.print(f"[error]Failed to download GGUF model: {exc}[/]")
        raise typer.Exit(code=1)

    size = ollama.format_size(size_bytes)
    console.print(f"[ok]Saved GGUF model: {dest} ({size})[/]")


@gguf_app.command(name="remove", context_settings=COMMAND_CONTEXT)
def remove_gguf_cmd(
    ctx: typer.Context,
    help_: bool = command_help_option(),
    name: str = typer.Argument(..., help="Filename of the GGUF model to delete."),
) -> None:
    """Delete a GGUF model from the local GGUF store."""

    maybe_show_command_help(ctx, help_)
    path = _gguf_dir() / name

    if not path.exists():
        console.print(f"[warn]GGUF model not found: {path}[/]")
        raise typer.Exit(code=1)

    path.unlink()
    console.print(f"[ok]Removed GGUF model: {path}[/]")


@gguf_app.command(name="search", context_settings=COMMAND_CONTEXT)
def search_gguf_cmd(
    ctx: typer.Context,
    query: Optional[str] = typer.Argument(
        None, help="Search query (model name or keywords)"
    ),
    limit: int = typer.Option(5, "--limit", "-l", help="Maximum results to return"),
    help_: bool = command_help_option(),
) -> None:
    """Search for GGUF models on HuggingFace."""

    maybe_show_command_help(ctx, help_)

    # Validate query is provided
    if not query:
        console.print("[error]Missing argument 'QUERY'[/]")
        console.print("Try 'airpods gguf search --help' for more information.")
        raise typer.Exit(1)

    console.print(f"Searching HuggingFace for [accent]{query}[/]...\n")

    try:
        hf_results = ollama.search_huggingface_models(query, limit)

        if hf_results:
            for model in hf_results:
                repo_id = model["repo_id"]
                downloads = model.get("downloads", 0)
                likes = model.get("likes", 0)
                url = f"https://huggingface.co/{repo_id}"

                # Build stats
                stats_parts = []
                if downloads > 0:
                    if downloads >= 1000:
                        stats_parts.append(f"↓ {downloads // 1000}K downloads")
                    else:
                        stats_parts.append(f"↓ {downloads} downloads")
                if likes > 0:
                    stats_parts.append(f"★ {likes} likes")

                stats = " - " + " • ".join(stats_parts) if stats_parts else ""
                console.print(f"  [accent]{repo_id}[/accent]{stats}")
                console.print(f"    [dim]→ [link={url}]{url}[/link][/dim]")

            console.print(
                "\n[dim]Tip: Pull with 'airpods gguf pull <repo>[:QUANT]'[/dim]"
            )
        else:
            console.print("[dim]No results found[/dim]")
            console.print(
                "\n[dim]Browse models: [link=https://huggingface.co/models?library=gguf]https://huggingface.co/models?library=gguf[/link][/dim]"
            )

    except ollama.OllamaAPIError as e:
        console.print(f"[error]Search failed: {e}[/]")
        raise typer.Exit(1)


def register(app: typer.Typer) -> CommandMap:
    """Register standalone GGUF commands."""
    app.add_typer(gguf_app, name="gguf")

    gguf_app.command(
        name="ls",
        help=ALIAS_HELP_TEMPLATE.format(canonical="list"),
        hidden=True,
        context_settings=COMMAND_CONTEXT,
    )(list_gguf_cmd)

    return {}
