"""Tests for the gguf search command."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from airpods.cli import app

runner = CliRunner()


@pytest.fixture
def mock_hf_search():
    """Mock HuggingFace search results."""
    return [
        {
            "repo_id": "bartowski/Llama-3.2-3B-Instruct-GGUF",
            "author": "bartowski",
            "model_name": "Llama-3.2-3B-Instruct-GGUF",
            "downloads": 125000,
            "likes": 42,
        },
        {
            "repo_id": "hugging-quants/Llama-3.2-1B-Instruct-GGUF",
            "author": "hugging-quants",
            "model_name": "Llama-3.2-1B-Instruct-GGUF",
            "downloads": 80000,
            "likes": 28,
        },
    ]


def test_gguf_search_basic(mock_hf_search):
    """Test basic search functionality."""
    with patch("airpods.ollama.search_huggingface_models") as mock_hf:
        mock_hf.return_value = mock_hf_search

        result = runner.invoke(app, ["gguf", "search", "llama"])

        assert result.exit_code == 0
        assert "Searching HuggingFace for llama" in result.stdout
        assert "bartowski/Llama-3.2-3B-Instruct-GGUF" in result.stdout
        assert "125K downloads" in result.stdout
        assert "42 likes" in result.stdout


def test_gguf_search_with_limit(mock_hf_search):
    """Test search with custom limit."""
    with patch("airpods.ollama.search_huggingface_models") as mock_hf:
        mock_hf.return_value = mock_hf_search

        result = runner.invoke(app, ["gguf", "search", "--limit", "10", "llama"])

        assert result.exit_code == 0
        # Verify the limit was passed
        mock_hf.assert_called_once_with("llama", 10)


def test_gguf_search_no_results():
    """Test search with no results."""
    with patch("airpods.ollama.search_huggingface_models") as mock_hf:
        mock_hf.return_value = []

        result = runner.invoke(app, ["gguf", "search", "nonexistent"])

        assert result.exit_code == 0
        assert "No results found" in result.stdout
        assert "Browse models:" in result.stdout


def test_gguf_search_missing_query():
    """Test search without providing a query."""
    result = runner.invoke(app, ["gguf", "search"])

    assert result.exit_code == 1
    assert "Missing argument" in result.stdout


def test_gguf_search_api_error():
    """Test search when API fails."""
    with patch("airpods.ollama.search_huggingface_models") as mock_hf:
        from airpods.ollama import OllamaAPIError

        mock_hf.side_effect = OllamaAPIError("API failed")

        result = runner.invoke(app, ["gguf", "search", "llama"])

        assert result.exit_code == 1
        assert "Search failed" in result.stdout
