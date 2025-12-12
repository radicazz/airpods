"""Ollama API wrapper for model management operations."""

from __future__ import annotations

import json
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Optional

import requests

from airpods.logging import console


class OllamaAPIError(Exception):
    """Raised when Ollama API returns an error."""


def get_ollama_url(port: int = 11434) -> str:
    """Get the Ollama API base URL."""
    return f"http://localhost:{port}"


def ensure_ollama_available(port: int = 11434, timeout: float = 2.0) -> bool:
    """
    Check if Ollama service is available and healthy.

    Args:
        port: Ollama API port (default: 11434)
        timeout: Connection timeout in seconds

    Returns:
        True if Ollama is available, False otherwise
    """
    try:
        response = requests.get(
            f"{get_ollama_url(port)}/api/tags",
            timeout=timeout,
        )
        return response.status_code == 200
    except (requests.RequestException, Exception):
        return False


def list_models(port: int = 11434) -> list[dict[str, Any]]:
    """
    List all installed Ollama models.

    Args:
        port: Ollama API port (default: 11434)

    Returns:
        List of model dictionaries with keys: name, modified_at, size, digest, details

    Raises:
        OllamaAPIError: If API request fails
    """
    try:
        response = requests.get(
            f"{get_ollama_url(port)}/api/tags",
            timeout=5.0,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("models", [])
    except requests.RequestException as e:
        raise OllamaAPIError(f"Failed to list models: {e}") from e


def show_model(name: str, port: int = 11434) -> dict[str, Any]:
    """
    Get detailed information about a specific model.

    Args:
        name: Model name (with optional tag, e.g., "llama3.2" or "llama3.2:7b")
        port: Ollama API port (default: 11434)

    Returns:
        Dictionary with model details including modelfile, parameters, template, etc.

    Raises:
        OllamaAPIError: If API request fails or model not found
    """
    try:
        response = requests.post(
            f"{get_ollama_url(port)}/api/show",
            json={"name": name},
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        raise OllamaAPIError(f"Failed to get model info for '{name}': {e}") from e


def pull_model(
    name: str,
    port: int = 11434,
    progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
) -> bool:
    """
    Pull a model from the Ollama library.

    Args:
        name: Model name (with optional tag, e.g., "llama3.2" or "llama3.2:7b")
        port: Ollama API port (default: 11434)
        progress_callback: Optional callback function called with progress updates
                          Receives dict with keys: status, digest, total, completed

    Returns:
        True if pull succeeded

    Raises:
        OllamaAPIError: If API request fails
    """
    try:
        response = requests.post(
            f"{get_ollama_url(port)}/api/pull",
            json={"name": name},
            stream=True,
            timeout=None,  # No timeout for long downloads
        )
        response.raise_for_status()

        # Stream progress updates
        for line in response.iter_lines():
            if line:
                try:
                    data = json.loads(line)
                    if progress_callback:
                        progress_callback(data)

                    # Check for errors in the response
                    if "error" in data:
                        raise OllamaAPIError(f"Pull failed: {data['error']}")
                except json.JSONDecodeError:
                    continue

        return True
    except requests.RequestException as e:
        raise OllamaAPIError(f"Failed to pull model '{name}': {e}") from e


def delete_model(name: str, port: int = 11434) -> bool:
    """
    Delete an installed model.

    Args:
        name: Model name (with optional tag, e.g., "llama3.2" or "llama3.2:7b")
        port: Ollama API port (default: 11434)

    Returns:
        True if deletion succeeded

    Raises:
        OllamaAPIError: If API request fails
    """
    try:
        response = requests.delete(
            f"{get_ollama_url(port)}/api/delete",
            json={"name": name},
            timeout=10.0,
        )
        response.raise_for_status()
        return True
    except requests.RequestException as e:
        raise OllamaAPIError(f"Failed to delete model '{name}': {e}") from e


def get_storage_usage(models: list[dict[str, Any]]) -> int:
    """
    Calculate total storage used by models.

    Args:
        models: List of model dictionaries from list_models()

    Returns:
        Total size in bytes
    """
    return sum(model.get("size", 0) for model in models)


def format_size(size_bytes: int) -> str:
    """
    Format bytes into human-readable size.

    Args:
        size_bytes: Size in bytes

    Returns:
        Formatted string (e.g., "2.3 GB", "150 MB")
    """
    if size_bytes == 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    size = float(size_bytes)

    while size >= 1024.0 and unit_index < len(units) - 1:
        size /= 1024.0
        unit_index += 1

    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    else:
        return f"{size:.1f} {units[unit_index]}"


def format_time_ago(timestamp_str: str) -> str:
    """
    Format ISO timestamp into human-readable relative time.

    Args:
        timestamp_str: ISO 8601 timestamp string

    Returns:
        Formatted string (e.g., "2 days ago", "3 hours ago")
    """
    try:
        from datetime import datetime, timezone

        # Parse the timestamp (handle both with and without microseconds)
        if "." in timestamp_str:
            timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        else:
            timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))

        now = datetime.now(timezone.utc)
        delta = now - timestamp

        seconds = delta.total_seconds()

        if seconds < 60:
            return "just now"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        elif seconds < 604800:
            days = int(seconds / 86400)
            return f"{days} day{'s' if days != 1 else ''} ago"
        elif seconds < 2592000:
            weeks = int(seconds / 604800)
            return f"{weeks} week{'s' if weeks != 1 else ''} ago"
        else:
            months = int(seconds / 2592000)
            return f"{months} month{'s' if months != 1 else ''} ago"
    except Exception:
        return timestamp_str


# HuggingFace Integration


def generate_model_name_from_repo(repo_id: str, filename: Optional[str] = None) -> str:
    """
    Generate a model name from HuggingFace repo ID and optional filename.

    Args:
        repo_id: HuggingFace repo ID (e.g., "bartowski/Llama-3.2-3B-Instruct-GGUF")
        filename: Optional GGUF filename to extract quantization info

    Returns:
        Suggested model name (e.g., "llama-32-3b-instruct" or "llama-32-3b-instruct-q4")
    """
    # Extract model name from repo (take part after /)
    if "/" in repo_id:
        name = repo_id.split("/", 1)[1]
    else:
        name = repo_id

    # Remove common suffixes
    name = re.sub(r"-(GGUF|gguf)$", "", name, flags=re.IGNORECASE)

    # If filename provided, try to extract quantization
    quant = ""
    if filename:
        # Look for quantization pattern like Q4_K_M, Q5_K_S, Q8_0, etc.
        quant_match = re.search(
            r"[_-](Q\d+_[KM0]+(?:_[SMLH])?)", filename, re.IGNORECASE
        )
        if quant_match:
            quant = f"-{quant_match.group(1).lower()}"

    # Convert to lowercase and replace non-alphanumeric with hyphens
    name = re.sub(r"[^a-zA-Z0-9]+", "-", name).lower()
    name = re.sub(r"-+", "-", name).strip("-")

    return f"{name}{quant}"


def list_gguf_files(repo_id: str) -> list[dict[str, Any]]:
    """
    List GGUF files available in a HuggingFace repository.

    Args:
        repo_id: HuggingFace repo ID (e.g., "bartowski/Llama-3.2-3B-Instruct-GGUF")

    Returns:
        List of dicts with keys: filename, size

    Raises:
        OllamaAPIError: If HF API fails or no GGUF files found
    """
    try:
        from huggingface_hub import list_repo_files, repo_info

        # List all files in the repo
        files = list_repo_files(repo_id)

        # Filter for GGUF files
        gguf_files = [f for f in files if f.lower().endswith(".gguf")]

        if not gguf_files:
            raise OllamaAPIError(f"No GGUF files found in repository '{repo_id}'")

        # Get file sizes
        info = repo_info(repo_id)
        result = []

        for filename in gguf_files:
            # Find size from sibling files
            size = 0
            for sibling in info.siblings:
                if sibling.rfilename == filename:
                    size = sibling.size or 0
                    break

            result.append(
                {
                    "filename": filename,
                    "size": size,
                }
            )

        # Sort by size (descending) for better UX
        result.sort(key=lambda x: x["size"], reverse=True)

        return result

    except ImportError as e:
        raise OllamaAPIError(
            "huggingface-hub not installed. Install with: uv pip install huggingface-hub"
        ) from e
    except Exception as e:
        raise OllamaAPIError(f"Failed to list GGUF files from '{repo_id}': {e}") from e


def pull_from_huggingface(
    repo_id: str,
    filename: str,
    model_name: str,
    port: int = 11434,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> bool:
    """
    Download a GGUF file from HuggingFace and import it into Ollama.

    Args:
        repo_id: HuggingFace repo ID (e.g., "bartowski/Llama-3.2-3B-Instruct-GGUF")
        filename: GGUF filename to download
        model_name: Name to give the model in Ollama
        port: Ollama API port (default: 11434)
        progress_callback: Optional callback called with (phase, current, total)
                          phase is "download" or "import"

    Returns:
        True if import succeeded

    Raises:
        OllamaAPIError: If download or import fails
    """
    try:
        from huggingface_hub import hf_hub_download
        import subprocess

        # Download from HuggingFace
        if progress_callback:
            progress_callback("download", 0, 100)

        try:
            local_path = hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                local_dir_use_symlinks=False,
            )
        except Exception as e:
            raise OllamaAPIError(f"Failed to download from HuggingFace: {e}") from e

        if progress_callback:
            progress_callback("download", 100, 100)

        # Create modelfile
        if progress_callback:
            progress_callback("import", 0, 100)

        modelfile_content = f"FROM {local_path}\n"

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".modelfile", delete=False
        ) as f:
            f.write(modelfile_content)
            modelfile_path = f.name

        try:
            # Import into Ollama via CLI (requires podman exec)
            # We'll use the Ollama container name from the service spec
            from airpods import podman

            # Copy modelfile into container
            container = "ollama-0"  # Default from config

            # First, check if we can reach the Ollama API
            if not ensure_ollama_available(port):
                raise OllamaAPIError(
                    "Ollama service not available. Start with 'airpods start ollama'"
                )

            # Use podman exec to run ollama create command
            result = subprocess.run(
                [
                    "podman",
                    "exec",
                    "-i",
                    container,
                    "sh",
                    "-c",
                    f"cat > /tmp/Modelfile && ollama create {model_name} -f /tmp/Modelfile",
                ],
                input=modelfile_content.encode(),
                capture_output=True,
                check=False,
            )

            if result.returncode != 0:
                error_msg = result.stderr.decode() if result.stderr else "Unknown error"
                raise OllamaAPIError(f"Failed to import model: {error_msg}")

            if progress_callback:
                progress_callback("import", 100, 100)

            return True

        finally:
            # Clean up modelfile
            Path(modelfile_path).unlink(missing_ok=True)

    except ImportError as e:
        raise OllamaAPIError(
            "huggingface-hub not installed. Install with: uv pip install huggingface-hub"
        ) from e
    except OllamaAPIError:
        raise
    except Exception as e:
        raise OllamaAPIError(f"Failed to import model from HuggingFace: {e}") from e
