"""Models command implementation for Ollama and GGUF model management."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Optional

import typer

from airpods import gguf, ollama, ui
from airpods.logging import console

from ..common import ALIAS_HELP_TEMPLATE, COMMAND_CONTEXT, get_ollama_port
from ..completions import model_name_completion
from ..help import command_help_option, maybe_show_command_help, show_command_help
from ..type_defs import CommandMap

# Create sub-app for models command
models_app = typer.Typer(
    help="Manage Ollama and GGUF models", context_settings=COMMAND_CONTEXT
)
gguf_app = typer.Typer(help="Manage GGUF model files", context_settings=COMMAND_CONTEXT)
models_app.add_typer(gguf_app, name="gguf")


@models_app.callback(invoke_without_command=True)
def _models_root(
    ctx: typer.Context,
    help_: bool = command_help_option(),
) -> None:
    """Entry point for the models command group."""
    maybe_show_command_help(ctx, help_)
    if ctx.invoked_subcommand is None:
        show_command_help(ctx)


@gguf_app.callback(invoke_without_command=True)
def _gguf_root(
    ctx: typer.Context,
    help_: bool = command_help_option(),
) -> None:
    """Entry point for the gguf command group."""
    maybe_show_command_help(ctx, help_)
    if ctx.invoked_subcommand is None:
        show_command_help(ctx)


def ensure_ollama_running() -> int:
    """
    Ensure Ollama service is running before executing model operations.

    Returns:
        Ollama port number

    Raises:
        typer.Exit: If Ollama is not running
    """
    port = get_ollama_port()

    if not ollama.ensure_ollama_available(port):
        console.print(
            "[error]Ollama is not running. Start with 'airpods start ollama'[/]"
        )
        raise typer.Exit(1)

    return port


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


@gguf_app.command(name="pull", context_settings=COMMAND_CONTEXT)
def pull_gguf_cmd(
    ctx: typer.Context,
    help_: bool = command_help_option(),
    url: str = typer.Argument(..., help="Direct URL to a GGUF file."),
    name: Optional[str] = typer.Option(
        None, "--name", "-n", help="Override the filename to save as."
    ),
) -> None:
    """Download a GGUF file into the local GGUF store."""

    maybe_show_command_help(ctx, help_)
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


@models_app.command(name="list", context_settings=COMMAND_CONTEXT)
def list_models_cmd(
    ctx: typer.Context,
    help_: bool = command_help_option(),
) -> None:
    """List all installed Ollama models."""

    maybe_show_command_help(ctx, help_)
    port = ensure_ollama_running()

    try:
        models_list = ollama.list_models(port)

        if not models_list:
            console.print("[info]No models installed[/]")
            console.print("Pull a model with 'airpods models pull <model>'")
            console.print(
                "\n[dim]Browse models:[/dim]\n"
                "  [dim]• Ollama library: [link=https://ollama.com/library]https://ollama.com/library[/link][/dim]\n"
                "  [dim]• HuggingFace GGUF: [link=https://huggingface.co/models?library=gguf]https://huggingface.co/models?library=gguf[/link][/dim]"
            )
            return

        # Create Rich table
        table = ui.themed_table()
        table.add_column("Model", no_wrap=True)
        table.add_column("Size", justify="right")
        table.add_column("Modified")
        table.add_column("Family")

        # Sort by modified date (newest first)
        sorted_models = sorted(
            models_list,
            key=lambda m: m.get("modified_at", ""),
            reverse=True,
        )

        for model in sorted_models:
            name = model.get("name", "unknown")
            size = ollama.format_size(model.get("size", 0))
            modified = ollama.format_time_ago(model.get("modified_at", ""))

            # Extract family from details if available
            family = ""
            if "details" in model and model["details"]:
                family = model["details"].get("family", "")

            table.add_row(name, size, modified, family)

        console.print(table)

        # Show total storage usage
        total_size = ollama.get_storage_usage(models_list)
        console.print(
            f"\n[dim]Total storage: {ollama.format_size(total_size)} "
            f"({len(models_list)} model{'s' if len(models_list) != 1 else ''})[/]"
        )

    except ollama.OllamaAPIError as e:
        console.print(f"[error]Failed to list models: {e}[/]")
        raise typer.Exit(1)


def _detect_model_source(model_spec: str) -> str:
    """
    Detect whether a model specification is for Ollama library or HuggingFace.

    Args:
        model_spec: Model specification (tag, repo, or URL)

    Returns:
        "huggingface" if it looks like a HF repo/URL, "ollama" otherwise
    """
    # Check for explicit Ollama URLs
    if "ollama.com" in model_spec.lower():
        return "ollama"

    # Check for obvious HuggingFace indicators
    if "huggingface.co" in model_spec.lower():
        return "huggingface"

    # Namespace/model patterns (owner/repo) are treated as HuggingFace repos.
    if "/" in model_spec:
        return "huggingface"

    return "ollama"


@models_app.command(name="pull", context_settings=COMMAND_CONTEXT)
def pull_model_cmd(
    ctx: typer.Context,
    help_: bool = command_help_option(),
    model: str = typer.Argument(
        ...,
        help="Model name or repo (e.g., llama3.2, qwen2.5:7b, bartowski/Llama-3.2-3B-Instruct-GGUF)",
    ),
    source: Optional[str] = typer.Option(
        None,
        "--source",
        "-s",
        help="Specify source: 'ollama' or 'huggingface' (auto-detected if not provided)",
    ),
    file: Optional[str] = typer.Option(
        None, "--file", "-f", help="GGUF filename (for HuggingFace repos)"
    ),
    name: Optional[str] = typer.Option(
        None, "--name", "-n", help="Model name in Ollama (for HuggingFace repos)"
    ),
) -> None:
    """Pull a model from Ollama library or HuggingFace (auto-detected)."""

    maybe_show_command_help(ctx, help_)
    port = ensure_ollama_running()

    # Validate source option if provided
    if source and source.lower() not in ("ollama", "huggingface", "hf"):
        console.print(
            f"[error]Invalid source '{source}'. Must be 'ollama' or 'huggingface'[/]"
        )
        raise typer.Exit(1)

    # Determine source (explicit or auto-detected)
    if source:
        detected_source = (
            "huggingface" if source.lower() in ("huggingface", "hf") else "ollama"
        )
        console.print(f"[dim]Using explicit source: [accent]{detected_source}[/][/dim]")
    else:
        detected_source = _detect_model_source(model)

    if detected_source == "huggingface":
        # Route to HuggingFace pull logic
        if not source:
            console.print(f"[dim]Detected HuggingFace repo: [accent]{model}[/][/dim]")
        _pull_from_huggingface(model, port, file, name)
    else:
        # Route to Ollama pull logic
        if not source:
            console.print(f"[dim]Pulling from Ollama library: [accent]{model}[/][/dim]")
        _pull_from_ollama(model, port)


def _pull_from_ollama(model: str, port: int) -> None:
    """Pull a model from the Ollama library."""
    try:
        from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
        import time

        # Track progress
        total_size = 0
        completed = 0
        last_status = ""
        start_time = time.time()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
        ) as progress:
            task = progress.add_task(f"Downloading {model}", total=100)

            def update_progress(data: dict) -> None:
                nonlocal total_size, completed, last_status

                status = data.get("status", "")

                # Update total if we receive it
                if "total" in data and data["total"]:
                    total_size = data["total"]

                # Update completed if we receive it
                if "completed" in data and data["completed"]:
                    completed = data["completed"]

                # Calculate percentage
                if total_size > 0:
                    percent = (completed / total_size) * 100
                    progress.update(task, completed=percent)

                    # Update description with status
                    if status and status != last_status:
                        progress.update(task, description=f"{status}")
                        last_status = status

            ollama.pull_model(model, port, progress_callback=update_progress)

        # Get final model info
        try:
            info = ollama.show_model(model, port)
            model_size = info.get("size", 0) if isinstance(info, dict) else 0
        except Exception:
            model_size = 0

        elapsed = time.time() - start_time
        size_str = ollama.format_size(model_size) if model_size else ""

        if size_str:
            console.print(f"[ok]✓ Model {model} ready ({size_str}, {elapsed:.1f}s)[/]")
        else:
            console.print(f"[ok]✓ Model {model} ready ({elapsed:.1f}s)[/]")

    except ollama.OllamaAPIError as e:
        console.print(f"[error]Failed to pull model: {e}[/]")
        raise typer.Exit(1)


def _pull_from_huggingface(
    repo: str, port: int, file: Optional[str] = None, name: Optional[str] = None
) -> None:
    """Pull a GGUF model from HuggingFace and import to Ollama."""
    try:
        # List available GGUF files
        console.print(f"Fetching GGUF files from [accent]{repo}[/]...")
        gguf_files = ollama.list_gguf_files(repo)

        # If no file specified, prompt user to select
        if not file:
            if len(gguf_files) == 1:
                file = gguf_files[0]["filename"]
                console.print(f"Found 1 GGUF file: [accent]{file}[/]")
            else:
                console.print(f"\nAvailable GGUF files in [accent]{repo}[/]:")
                for i, gguf in enumerate(gguf_files, 1):
                    size_str = ollama.format_size(gguf["size"])
                    console.print(f"  {i}. {gguf['filename']} ({size_str})")

                # Prompt for selection
                while True:
                    selection = typer.prompt(
                        f"\nSelect file [1-{len(gguf_files)}]", type=int
                    )
                    if 1 <= selection <= len(gguf_files):
                        file = gguf_files[selection - 1]["filename"]
                        break
                    console.print(
                        f"[error]Invalid selection. Please choose 1-{len(gguf_files)}[/]"
                    )

        # Validate file exists
        if not any(f["filename"] == file for f in gguf_files):
            console.print(f"[error]File '{file}' not found in repository[/]")
            raise typer.Exit(1)

        # If no name specified, generate and prompt
        if not name:
            suggested_name = ollama.generate_model_name_from_repo(repo, file)
            console.print(f"\nSuggested name: [accent]{suggested_name}[/]")

            response = typer.prompt(
                "Accept? [Y/n] or enter custom name",
                default="Y",
                show_default=False,
            )

            if response.lower() in ("y", "yes", ""):
                name = suggested_name
            else:
                name = response.strip()

        # Validate name
        if not name:
            console.print("[error]Model name cannot be empty[/]")
            raise typer.Exit(1)

        console.print(f"\nDownloading [accent]{file}[/] from HuggingFace...")

        # Track progress
        download_phase = True

        from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
        ) as progress:
            download_task = progress.add_task("Downloading from HuggingFace", total=100)
            import_task = progress.add_task(
                "Importing to Ollama", total=100, visible=False
            )

            def update_progress(phase: str, current: int, total: int) -> None:
                nonlocal download_phase

                if phase == "download":
                    if download_phase:
                        progress.update(download_task, completed=current)
                    else:
                        # Download complete
                        progress.update(download_task, completed=100, visible=False)
                        progress.update(import_task, visible=True)
                        download_phase = False
                elif phase == "import":
                    progress.update(import_task, completed=current)

            ollama.pull_from_huggingface(
                repo, file, name, port, progress_callback=update_progress
            )

        console.print(f"[ok]✓ Model {name} imported successfully[/]")
        console.print(f"Test with: [dim]ollama run {name}[/]")

    except ollama.OllamaAPIError as e:
        console.print(f"[error]Failed to import model: {e}[/]")
        raise typer.Exit(1)


@models_app.command(name="remove", context_settings=COMMAND_CONTEXT)
def remove_model_cmd(
    ctx: typer.Context,
    help_: bool = command_help_option(),
    model: str = typer.Argument(
        ..., help="Model name to remove", shell_complete=model_name_completion
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
) -> None:
    """Remove an installed model."""

    maybe_show_command_help(ctx, help_)
    port = ensure_ollama_running()

    try:
        # Verify model exists
        models_list = ollama.list_models(port)
        if not any(m.get("name") == model for m in models_list):
            console.print(f"[error]Model '{model}' not found[/]")
            raise typer.Exit(1)

        # Confirm deletion unless --force
        if not force:
            confirm = typer.confirm(f"Remove model '{model}'?", default=False)
            if not confirm:
                console.print("[info]Cancelled[/]")
                return

        # Delete the model
        ollama.delete_model(model, port)
        console.print(f"[ok]✓ Model {model} removed[/]")

    except ollama.OllamaAPIError as e:
        console.print(f"[error]Failed to remove model: {e}[/]")
        raise typer.Exit(1)


@models_app.command(name="info", context_settings=COMMAND_CONTEXT)
def info_model_cmd(
    ctx: typer.Context,
    help_: bool = command_help_option(),
    model: str = typer.Argument(
        ..., help="Model name", shell_complete=model_name_completion
    ),
) -> None:
    """Show detailed information about a model."""

    maybe_show_command_help(ctx, help_)
    port = ensure_ollama_running()

    try:
        info = ollama.show_model(model, port)

        # Display model information
        from rich.panel import Panel
        from rich.text import Text

        # Build info text
        info_lines = []
        info_lines.append(f"[bold]Model:[/bold] {model}")

        # Show license if available
        if "license" in info:
            info_lines.append(f"[bold]License:[/bold] {info['license']}")

        # Show family if available
        if "details" in info and isinstance(info["details"], dict):
            details = info["details"]
            if "family" in details:
                info_lines.append(f"[bold]Family:[/bold] {details['family']}")
            if "parameter_size" in details:
                info_lines.append(
                    f"[bold]Parameters:[/bold] {details['parameter_size']}"
                )
            if "quantization_level" in details:
                info_lines.append(
                    f"[bold]Quantization:[/bold] {details['quantization_level']}"
                )

        # Show size if available
        if "size" in info:
            size_str = ollama.format_size(info["size"])
            info_lines.append(f"[bold]Size:[/bold] {size_str}")

        # Show modelfile
        if "modelfile" in info:
            info_lines.append(f"\n[bold]Modelfile:[/bold]")
            info_lines.append(f"[dim]{info['modelfile']}[/dim]")

        # Show parameters
        if "parameters" in info:
            info_lines.append(f"\n[bold]Parameters:[/bold]")
            info_lines.append(f"[dim]{info['parameters']}[/dim]")

        # Show template if available
        if "template" in info:
            info_lines.append(f"\n[bold]Template:[/bold]")
            # Truncate long templates
            template = info["template"]
            if len(template) > 200:
                template = template[:200] + "..."
            info_lines.append(f"[dim]{template}[/dim]")

        panel = Panel(
            "\n".join(info_lines),
            title=f"[info]Model Information[/]",
            border_style="cyan",
        )

        console.print(panel)

    except ollama.OllamaAPIError as e:
        console.print(f"[error]Failed to get model info: {e}[/]")
        raise typer.Exit(1)


@models_app.command(name="search", context_settings=COMMAND_CONTEXT)
def search_models_cmd(
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
        console.print("Try 'airpods models search --help' for more information.")
        raise typer.Exit(1)

    console.print(f"Searching HuggingFace for [accent]{query}[/]...\n")

    try:
        hf_results = ollama.search_huggingface_models(query, limit)

        if hf_results:
            for model in hf_results:
                repo_id = model["repo_id"]
                author = model["author"]
                model_name = model["model_name"]
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
                f"\n[dim]Tip: Pull with 'airpods models pull <repo> --source huggingface'[/dim]"
            )
        else:
            console.print("[dim]No results found[/dim]")
            console.print(
                f"\n[dim]Browse models: [link=https://ollama.com/library]https://ollama.com/library[/link][/dim]"
            )
            console.print(
                f"[dim]               [link=https://huggingface.co/models?library=gguf]https://huggingface.co/models?library=gguf[/link][/dim]"
            )

    except ollama.OllamaAPIError as e:
        console.print(f"[error]Search failed: {e}[/]")
        raise typer.Exit(1)


def register(app: typer.Typer) -> CommandMap:
    """Register the models command and its subcommands."""
    app.add_typer(models_app, name="models")
    app.add_typer(models_app, name="model", hidden=True)

    # Register hidden aliases for subcommands inside the models group (and gguf).
    # This prevents them from appearing as separate rows in `models --help` while
    # letting the help renderer show them (e.g. "list  ls") via COMMAND_ALIAS_GROUPS,
    # and still allows invocation (e.g. `airpods models ls`).
    models_app.command(
        name="ls",
        help=ALIAS_HELP_TEMPLATE.format(canonical="list"),
        hidden=True,
        context_settings=COMMAND_CONTEXT,
    )(list_models_cmd)

    models_app.command(
        name="rm",
        help=ALIAS_HELP_TEMPLATE.format(canonical="remove"),
        hidden=True,
        context_settings=COMMAND_CONTEXT,
    )(remove_model_cmd)

    gguf_app.command(
        name="ls",
        help=ALIAS_HELP_TEMPLATE.format(canonical="list"),
        hidden=True,
        context_settings=COMMAND_CONTEXT,
    )(list_gguf_cmd)

    return {}
