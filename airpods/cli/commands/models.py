"""Models command implementation for Ollama model management."""

from __future__ import annotations

from typing import Optional

import typer
from rich.table import Table

from airpods import ollama
from airpods.logging import console

from ..common import COMMAND_CONTEXT, get_ollama_port
from ..help import command_help_option, maybe_show_command_help
from ..type_defs import CommandMap

# Create sub-app for models command
models_app = typer.Typer(help="Manage Ollama models", no_args_is_help=True)


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


@models_app.command(name="list", context_settings=COMMAND_CONTEXT)
def list_models_cmd(
    help_: bool = command_help_option(),
) -> None:
    """List all installed Ollama models."""
    
    port = ensure_ollama_running()
    
    try:
        models_list = ollama.list_models(port)
        
        if not models_list:
            console.print("[info]No models installed[/]")
            console.print(
                "Pull a model with 'airpods models pull <model>' or "
                "'airpods models pull-hf <repo>'"
            )
            return
        
        # Create Rich table
        table = Table(title="[info]Installed Models")
        table.add_column("Model", style="cyan", no_wrap=True)
        table.add_column("Size", style="dim", justify="right")
        table.add_column("Modified", style="dim")
        table.add_column("Family", style="dim")
        
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


@models_app.command(name="pull", context_settings=COMMAND_CONTEXT)
def pull_model_cmd(
    model: str = typer.Argument(..., help="Model name (e.g., llama3.2, qwen2.5:7b)"),
    help_: bool = command_help_option(),
) -> None:
    """Pull a model from the Ollama library."""
    
    port = ensure_ollama_running()
    
    try:
        from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
        import time
        
        console.print(f"Pulling [accent]{model}[/]...")
        
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
            console.print(
                f"[ok]✓ Model {model} ready ({size_str}, {elapsed:.1f}s)[/]"
            )
        else:
            console.print(f"[ok]✓ Model {model} ready ({elapsed:.1f}s)[/]")
        
    except ollama.OllamaAPIError as e:
        console.print(f"[error]Failed to pull model: {e}[/]")
        raise typer.Exit(1)


def register(app: typer.Typer) -> CommandMap:
    """Register the models command and its subcommands."""
    app.add_typer(models_app, name="models")
    
    # Return empty dict since this is a typer sub-app
    # Aliases will be handled in common.py
    return {}
