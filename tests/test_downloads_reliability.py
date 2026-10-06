"""Regression coverage for downloads reliability."""

from __future__ import annotations

import io
from http.client import IncompleteRead
from unittest.mock import MagicMock
from urllib.request import Request

import pytest

from airpods import gguf
from airpods.cli import app
from airpods.cli.commands import workflows
from airpods.configuration.schema import CustomNodeInstall
from airpods.files import (
    DownloadError,
    SafeRedirectHandler,
    download_file,
    managed_path,
)


@pytest.mark.parametrize(
    "part", ["../outside", "/tmp/outside", "folder/../../outside", "folder\\outside"]
)
def test_download_destinations_reject_escaping_paths(tmp_path, part):
    with pytest.raises(ValueError):
        managed_path(tmp_path / "models", part)
    with pytest.raises(ValueError):
        gguf.download_model("https://example.com/model.gguf", name=part)


def test_destinations_reject_symlink_parents(tmp_path):
    root = tmp_path / "models"
    root.mkdir()
    (root / "link").symlink_to(tmp_path)
    with pytest.raises(ValueError):
        managed_path(root, "link", "model.gguf")
    assert (
        managed_path(root, "loras", "nested", "model.gguf")
        == root / "loras" / "nested" / "model.gguf"
    )


@pytest.mark.parametrize(
    "name", ["..", "../node", "/tmp/node", "nested/node", "nested\\node"]
)
def test_custom_nodes_reject_escaping_names(name):
    with pytest.raises(ValueError):
        CustomNodeInstall(name=name, repo="https://example.com/node.git")


def test_workflow_pull_rejects_traversal_before_download(runner, monkeypatch, tmp_path):
    root = tmp_path / "models"
    monkeypatch.setattr(workflows, "comfyui_models_dir", lambda: root)
    downloader = MagicMock()
    monkeypatch.setattr(workflows, "_download_to_path", downloader)
    result = runner.invoke(
        app,
        [
            "workflows",
            "pull",
            "https://example.com/model.gguf",
            "--folder",
            "../../outside",
        ],
    )
    assert result.exit_code != 0
    downloader.assert_not_called()
    assert not root.exists()


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://huggingface.co/model", True),
        ("https://example.com/model", False),
        ("http://huggingface.co/model", False),
        ("https://huggingface.co.example.com/model", False),
    ],
)
def test_hf_credentials_are_origin_restricted(url, expected, tmp_path):
    requests = []

    def opener(request, **kwargs):
        requests.append(request)
        response = io.BytesIO(b"model")
        response.headers = {"Content-Length": "5"}
        return response

    dest = tmp_path / "model.gguf"
    assert (
        download_file(
            url, dest, hf_token="placeholder", opener=opener, show_progress=False
        )
        == 5
    )
    assert bool(requests[0].get_header("Authorization")) is expected
    assert dest.read_bytes() == b"model"


def test_redirect_drops_credentials_for_other_origins():
    request = Request(
        "https://huggingface.co/model", headers={"Authorization": "Bearer placeholder"}
    )
    handler = SafeRedirectHandler()
    redirected = handler.redirect_request(
        request, None, 302, "Found", {}, "https://cdn.example.com/model"
    )
    assert redirected.get_header("Authorization") is None
    same = handler.redirect_request(
        request, None, 302, "Found", {}, "https://huggingface.co/other"
    )
    assert same.get_header("Authorization") == "Bearer placeholder"


def test_incomplete_download_keeps_existing_file(tmp_path):
    dest = tmp_path / "model.gguf"
    dest.write_bytes(b"existing")

    def opener(request, **kwargs):
        response = io.BytesIO(b"partial")
        response.headers = {"Content-Length": "100"}
        return response

    with pytest.raises(DownloadError, match="incomplete"):
        download_file(
            "https://example.com/model",
            dest,
            overwrite=True,
            retries=0,
            opener=opener,
            show_progress=False,
        )
    assert dest.read_bytes() == b"existing"
    assert list(tmp_path.iterdir()) == [dest]


@pytest.mark.parametrize(
    "requirements",
    ["../requirements.txt", "/tmp/requirements.txt", "folder\\requirements.txt"],
)
def test_custom_node_requirements_stay_in_node_directory(requirements):
    with pytest.raises(ValueError):
        CustomNodeInstall(
            name="example",
            repo="https://example.com/node.git",
            requirements=requirements,
        )


def test_download_retries_interrupted_http_response(tmp_path, monkeypatch):
    calls = []

    def opener(*args, **kwargs):
        response = io.BytesIO(b"model")
        response.headers = {"Content-Length": "5"}
        if not calls:
            response.read = MagicMock(side_effect=IncompleteRead(b"part", 1))
        calls.append(response)
        return response

    monkeypatch.setattr("airpods.files.time.sleep", lambda seconds: None)
    dest = tmp_path / "model.gguf"
    download_file("https://example.com/model", dest, opener=opener, show_progress=False)
    assert len(calls) == 2
    assert dest.read_bytes() == b"model"
    assert list(tmp_path.iterdir()) == [dest]
