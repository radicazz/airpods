"""Tests for pulling GGUF files from HuggingFace via owner/repo[:QUANT]."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from airpods import gguf, ollama
from airpods.cli import app

runner = CliRunner()


def _f(name: str, size: int = 100) -> dict:
    return {"filename": name, "size": size}


FILES = [
    _f("Qwen-4B-Q8_0.gguf", 400),
    _f("Qwen-4B-Q4_K_M.gguf", 200),
    _f("Qwen-4B-Q4_K_S.gguf", 190),
    _f("mmproj-F16.gguf", 50),
]


@pytest.mark.parametrize(
    "spec,expected",
    [
        ("owner/repo:Q4_K_M", ("owner/repo", "Q4_K_M")),
        ("owner/repo", ("owner/repo", None)),
        ("hf.co/owner/repo:Q8_0", ("owner/repo", "Q8_0")),
        ("https://huggingface.co/owner/repo/resolve/main/a.gguf", None),
        ("just-a-name", None),
    ],
)
def test_parse_hf_spec(spec, expected):
    assert gguf.parse_hf_spec(spec) == expected


def test_match_quant_is_token_exact():
    groups = gguf.group_model_files(FILES)
    assert len(groups) == 3  # mmproj excluded
    assert [g[0]["filename"] for g in gguf.match_quant(groups, "q4_k_m")] == [
        "Qwen-4B-Q4_K_M.gguf"
    ]
    assert gguf.match_quant(groups, "Q4_K") == []


def test_shards_grouped():
    files = [_f("m-Q4_K_M-00001-of-00002.gguf"), _f("m-Q4_K_M-00002-of-00002.gguf")]
    groups = gguf.group_model_files(files)
    assert len(groups) == 1 and len(groups[0]) == 2


@pytest.fixture
def downloads():
    calls = []

    def fake(repo, path, name=None, hf_token=None):
        calls.append((repo, path, name))
        return Path("/tmp") / (name or path), 1

    with (
        patch("airpods.gguf.download_hf_file", side_effect=fake),
        patch("airpods.ollama.list_gguf_files", return_value=FILES),
    ):
        yield calls


def test_explicit_quant_prompts_for_mmproj_yes(downloads):
    result = runner.invoke(app, ["models", "gguf", "pull", "o/r:Q4_K_M"], input="y\n")
    assert result.exit_code == 0, result.output
    assert [c[1] for c in downloads] == ["Qwen-4B-Q4_K_M.gguf", "mmproj-F16.gguf"]


def test_mmproj_declined(downloads):
    result = runner.invoke(app, ["models", "gguf", "pull", "o/r:Q8_0"], input="n\n")
    assert result.exit_code == 0, result.output
    assert [c[1] for c in downloads] == ["Qwen-4B-Q8_0.gguf"]


def test_default_quant_is_q4_k_m(downloads):
    result = runner.invoke(app, ["models", "gguf", "pull", "o/r", "--yes"])
    assert result.exit_code == 0, result.output
    assert [c[1] for c in downloads] == ["Qwen-4B-Q4_K_M.gguf"]


def test_mmproj_flag_with_yes(downloads):
    result = runner.invoke(app, ["models", "gguf", "pull", "o/r", "-y", "--mmproj"])
    assert result.exit_code == 0, result.output
    assert len(downloads) == 2


@pytest.mark.parametrize("flags", [[], ["--yes"]])
def test_unknown_quant_errors(downloads, flags):
    result = runner.invoke(app, ["models", "gguf", "pull", "o/r:Q2_K", *flags])
    assert result.exit_code == 1
    assert downloads == []
    assert "No file matches quant" in result.output


def test_multiple_projectors_with_yes_does_not_prompt(downloads):
    with patch(
        "airpods.ollama.list_gguf_files",
        return_value=[*FILES, _f("mmproj-Q8_0.gguf")],
    ):
        result = runner.invoke(
            app, ["models", "gguf", "pull", "o/r", "--yes", "--mmproj"]
        )
    assert result.exit_code == 1
    assert "Multiple mmproj files" in result.output
    assert downloads == []


def test_hf_token_passed_to_discovery_and_download(downloads):
    with patch("airpods.ollama.list_gguf_files", return_value=FILES) as listing:
        with patch("airpods.gguf.download_hf_file") as download:
            download.return_value = (Path("/tmp/model.gguf"), 1)
            result = runner.invoke(
                app,
                ["models", "gguf", "pull", "o/r", "--yes", "--hf-token", "test-token"],
            )
    assert result.exit_code == 0, result.output
    listing.assert_called_once_with("o/r", hf_token="test-token")
    assert download.call_args.kwargs["hf_token"] == "test-token"


def test_discovery_authenticates_hub_requests():
    from types import SimpleNamespace

    with (
        patch(
            "huggingface_hub.list_repo_files", return_value=["model.gguf"]
        ) as listing,
        patch(
            "huggingface_hub.repo_info",
            return_value=SimpleNamespace(
                siblings=[SimpleNamespace(rfilename="model.gguf", size=123)]
            ),
        ) as info,
    ):
        assert ollama.list_gguf_files("o/r", hf_token="test-token") == [
            _f("model.gguf", 123)
        ]
    listing.assert_called_once_with("o/r", token="test-token")
    info.assert_called_once_with("o/r", token="test-token")


def test_missing_default_quant_prompts_selection(downloads):
    files = [_f("a-Q8_0.gguf"), _f("a-Q5_0.gguf")]
    with patch("airpods.ollama.list_gguf_files", return_value=files):
        result = runner.invoke(app, ["models", "gguf", "pull", "o/r"], input="1\n")
    assert result.exit_code == 0, result.output
    assert [c[1] for c in downloads] == ["a-Q5_0.gguf"]


def test_url_pull_unchanged():
    with patch(
        "airpods.gguf.download_model", return_value=(Path("/tmp/x.gguf"), 5)
    ) as dm:
        result = runner.invoke(
            app, ["models", "gguf", "pull", "https://example.com/x.gguf"]
        )
    assert result.exit_code == 0
    dm.assert_called_once()
