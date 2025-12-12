"""Ollama API wrapper for model management operations."""

from __future__ import annotations

import json
import re
import subprocess
import uuid
from typing import Any, Callable, Optional

import requests


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


def search_huggingface_models(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """
    Search HuggingFace for GGUF models matching the query.

    Args:
        query: Search query (model name, keywords, etc.)
        limit: Maximum number of results to return

    Returns:
        List of dicts with keys: repo_id, author, model_name, downloads, likes

    Raises:
        OllamaAPIError: If HF API fails
    """
    try:
        from huggingface_hub import HfApi

        api = HfApi()

        # Search for models with GGUF in the name/tags
        models = api.list_models(
            search=f"{query} GGUF",
            sort="downloads",
            direction=-1,
            limit=limit * 3,  # Get more to filter
        )

        results = []
        for model in models:
            # Filter for models that likely contain GGUF files
            if "gguf" in model.id.lower() or (
                model.tags and "gguf" in " ".join(model.tags).lower()
            ):
                repo_parts = model.id.split("/")
                results.append(
                    {
                        "repo_id": model.id,
                        "author": repo_parts[0] if len(repo_parts) > 1 else "unknown",
                        "model_name": repo_parts[1]
                        if len(repo_parts) > 1
                        else repo_parts[0],
                        "downloads": getattr(model, "downloads", 0),
                        "likes": getattr(model, "likes", 0),
                    }
                )

                if len(results) >= limit:
                    break

        return results

    except ImportError as e:
        raise OllamaAPIError(
            "huggingface-hub not installed. Install with: uv pip install huggingface-hub"
        ) from e
    except Exception as e:
        raise OllamaAPIError(f"Failed to search HuggingFace: {e}") from e


def search_ollama_library(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """
    Search Ollama's public library for models.

    Note: This uses a best-effort approach since Ollama doesn't have a public search API.
    We'll return popular models that match the query.

    Args:
        query: Search query (model name, keywords, etc.)
        limit: Maximum number of results to return

    Returns:
        List of dicts with keys: name, description, tags
    """
    query_lower = query.lower()

    # Curated list of popular Ollama models with metadata
    # This could be enhanced by scraping ollama.ai/library or using their API if available
    popular_models = [
        {
            "name": "llama3.2",
            "description": "Meta's Llama 3.2 model",
            "tags": ["llama", "meta", "instruct", "3b", "1b"],
            "size": "small",
        },
        {
            "name": "llama3.2:3b",
            "description": "Meta's Llama 3.2 3B model",
            "tags": ["llama", "meta", "instruct"],
            "size": "small",
        },
        {
            "name": "llama3.1",
            "description": "Meta's Llama 3.1 model",
            "tags": ["llama", "meta", "instruct", "8b", "70b", "405b"],
            "size": "medium",
        },
        {
            "name": "llama3.1:8b",
            "description": "Meta's Llama 3.1 8B model",
            "tags": ["llama", "meta", "instruct"],
            "size": "medium",
        },
        {
            "name": "qwen2.5",
            "description": "Alibaba's Qwen 2.5 model",
            "tags": ["qwen", "alibaba", "instruct"],
            "size": "medium",
        },
        {
            "name": "qwen2.5:7b",
            "description": "Alibaba's Qwen 2.5 7B model",
            "tags": ["qwen", "alibaba", "instruct"],
            "size": "medium",
        },
        {
            "name": "mistral",
            "description": "Mistral AI's 7B model",
            "tags": ["mistral", "instruct"],
            "size": "medium",
        },
        {
            "name": "mixtral",
            "description": "Mistral AI's MoE model",
            "tags": ["mistral", "moe", "instruct"],
            "size": "large",
        },
        {
            "name": "phi3",
            "description": "Microsoft's Phi-3 model",
            "tags": ["phi", "microsoft", "small"],
            "size": "small",
        },
        {
            "name": "gemma2",
            "description": "Google's Gemma 2 model",
            "tags": ["gemma", "google"],
            "size": "medium",
        },
        {
            "name": "deepseek-coder",
            "description": "DeepSeek's coding model",
            "tags": ["deepseek", "code", "programming"],
            "size": "medium",
        },
        {
            "name": "codellama",
            "description": "Meta's Code Llama model",
            "tags": ["llama", "code", "programming"],
            "size": "medium",
        },
        {
            "name": "starcoder2",
            "description": "StarCoder 2 coding model",
            "tags": ["starcoder", "code", "programming"],
            "size": "medium",
        },
        {
            "name": "llava",
            "description": "Vision-language model",
            "tags": ["vision", "multimodal", "image"],
            "size": "medium",
        },
        {
            "name": "nous-hermes",
            "description": "Nous Research Hermes model",
            "tags": ["nous", "hermes", "instruct"],
            "size": "medium",
        },
    ]

    # Score each model based on query match
    scored_models = []
    for model in popular_models:
        score = 0

        # Exact name match gets highest score
        if query_lower == model["name"].lower():
            score += 100
        # Partial name match
        elif query_lower in model["name"].lower():
            score += 50

        # Tag matches
        for tag in model["tags"]:
            if query_lower in tag.lower():
                score += 10

        # Description match
        if query_lower in model["description"].lower():
            score += 5

        if score > 0:
            scored_models.append((score, model))

    # Sort by score (descending) and return top results
    scored_models.sort(key=lambda x: x[0], reverse=True)
    return [model for score, model in scored_models[:limit]]


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
        import airpods.config as config_module

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

        # Resolve container name from config (fallback to default)
        spec = config_module.REGISTRY.get("ollama")
        container = spec.container if spec and spec.container else "ollama-0"

        # Ensure service is up before attempting to copy
        if not ensure_ollama_available(port):
            raise OllamaAPIError(
                "Ollama service not available. Start with 'airpods start ollama'"
            )

        if progress_callback:
            progress_callback("import", 0, 100)

        # Use unique filename to avoid race conditions with concurrent imports
        unique_id = uuid.uuid4().hex
        remote_model_path = f"/tmp/model-{unique_id}.gguf"
        modelfile_content = f"FROM {remote_model_path}\n"

        # Copy GGUF file into the container
        try:
            subprocess.run(
                ["podman", "cp", local_path, f"{container}:{remote_model_path}"],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode() if exc.stderr else ""
            raise OllamaAPIError(
                f"Failed to copy model into container '{container}': {stderr or exc}"
            ) from exc

        # Create the model inside the container, piping the Modelfile via stdin
        result = subprocess.run(
            [
                "podman",
                "exec",
                "-i",
                container,
                "ollama",
                "create",
                model_name,
                "-f",
                "/dev/stdin",
            ],
            input=modelfile_content.encode(),
            capture_output=True,
            check=False,
        )

        if result.returncode != 0:
            stderr = result.stderr.decode() if result.stderr else "Unknown error"
            raise OllamaAPIError(f"Failed to import model: {stderr}")

        # Try to clean up the copied file; ignore failures
        subprocess.run(
            ["podman", "exec", container, "rm", "-f", remote_model_path],
            check=False,
            capture_output=True,
        )

        if progress_callback:
            progress_callback("import", 100, 100)

        return True

    except ImportError as e:
        raise OllamaAPIError(
            "huggingface-hub not installed. Install with: uv pip install huggingface-hub"
        ) from e
    except OllamaAPIError:
        raise
    except Exception as e:
        raise OllamaAPIError(f"Failed to import model from HuggingFace: {e}") from e
