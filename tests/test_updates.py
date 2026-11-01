from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from airpods import __version__
from airpods.state import clear_state_root_override, set_state_root
from airpods.updates import (
    InstallSource,
    ReleaseInfo,
    check_for_update,
    detect_install_source,
    fetch_latest_release,
    format_upgrade_hint,
    is_update_available,
)


def test_is_update_available_compares_versions():
    newer = ReleaseInfo(tag="v999.0.0", version="999.0.0", html_url="")
    assert is_update_available(newer) is True

    same = ReleaseInfo(tag=f"v{__version__}", version=__version__, html_url="")
    assert is_update_available(same) is False


def test_format_upgrade_hint_varies_by_channel():
    latest = ReleaseInfo(tag="v9.9.9", version="9.9.9", html_url="")

    nightly = format_upgrade_hint(
        latest, InstallSource(kind="nightly", revision="main")
    )
    assert "uv tool upgrade airpods" in nightly

    stable = format_upgrade_hint(latest, InstallSource(kind="tag", revision="v0.0.1"))
    assert "git+https://github.com/radicazz/airpods.git@v9.9.9" in stable


def test_check_for_update_uses_cache(tmp_path):
    set_state_root(tmp_path)
    try:
        latest = ReleaseInfo(tag="v1.2.3", version="1.2.3", html_url="x")

        with patch(
            "airpods.updates.fetch_latest_release", return_value=latest
        ) as fetch:
            first = check_for_update(force=True, interactive_only=False)
            assert first == latest
            assert fetch.call_count == 1

        # Ensure cache file exists and subsequent call can read it without fetching.
        cache_path = tmp_path / "configs" / "update_check.json"
        assert cache_path.exists()
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        assert cached["tag"] == "v1.2.3"

        with patch("airpods.updates.fetch_latest_release") as fetch2:
            second = check_for_update(force=False, interactive_only=False)
            assert second == latest
            fetch2.assert_not_called()
    finally:
        clear_state_root_override()


def test_detect_install_source_reads_direct_url_metadata():
    def _fake_distribution(_name: str):
        direct_url = {
            "vcs_info": {
                "requested_revision": "main",
                "commit_id": "deadbeef",
            }
        }
        return SimpleNamespace(
            read_text=lambda path: (
                json.dumps(direct_url) if path == "direct_url.json" else None
            )
        )

    with patch("importlib.metadata.distribution", _fake_distribution):
        src = detect_install_source()
        assert src.kind == "nightly"


def test_fetch_latest_release_parses_pyproject_toml():
    """Test that fetch_latest_release correctly parses version from pyproject.toml."""
    mock_response = type(
        "Response",
        (),
        {
            "text": """[project]
name = "airpods"
version = "1.2.3"
description = "Test"
""",
            "raise_for_status": lambda self: None,
        },
    )()

    with patch("airpods.updates.requests.get", return_value=mock_response):
        result = fetch_latest_release()
        assert result.version == "1.2.3"
        assert result.tag == "v1.2.3"
        assert "github.com/radicazz/airpods" in result.html_url


def test_detect_install_source_falls_back_on_missing_or_bad_metadata():
    from importlib.metadata import PackageNotFoundError

    def _missing(_name):
        raise PackageNotFoundError("airpods")

    with patch("importlib.metadata.distribution", _missing):
        assert detect_install_source().kind == "wheel_or_index"

    def _bad_json(_name):
        return SimpleNamespace(read_text=lambda _f: "{not json")

    with patch("importlib.metadata.distribution", _bad_json):
        assert detect_install_source().kind == "wheel_or_index"


def test_check_for_update_returns_none_on_network_failure(tmp_path, monkeypatch):
    import requests

    from airpods import updates

    monkeypatch.delenv("AIRPODS_NO_UPDATE_CHECK", raising=False)
    set_state_root(tmp_path)
    try:

        def _boom(**_kw):
            raise requests.ConnectionError("offline")

        with patch.object(updates, "fetch_latest_release", _boom):
            assert updates.check_for_update(force=True, interactive_only=False) is None
    finally:
        clear_state_root_override()
