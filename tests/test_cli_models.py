from __future__ import annotations

from airpods.cli.commands.models import _detect_model_source


def test_detect_model_source_owner_repo_defaults_to_huggingface():
    assert _detect_model_source("bartowski/Llama-3.2-3B-Instruct-GGUF") == "huggingface"


def test_detect_model_source_plain_tag_defaults_to_ollama():
    assert _detect_model_source("llama3.2") == "ollama"


def test_detect_model_source_ollama_url_stays_ollama():
    assert _detect_model_source("https://ollama.com/library/llama3.2") == "ollama"
