from __future__ import annotations

import io
import json
import tarfile
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from airpods.cli import app


@pytest.fixture
def mock_state_dirs(tmp_path):
    home = tmp_path / "airpods-home"
    configs = home / "configs"
    volumes = home / "volumes"
    configs.mkdir(parents=True, exist_ok=True)
    volumes.mkdir(parents=True, exist_ok=True)

    with (
        patch("airpods.cli.commands.backup.configs_dir", return_value=configs),
        patch("airpods.cli.commands.backup.volumes_dir", return_value=volumes),
    ):
        yield {"home": home, "configs": configs, "volumes": volumes}


@pytest.fixture
def mock_podman():
    with patch("airpods.cli.commands.backup.ensure_runtime_available"):
        yield


@pytest.fixture
def mock_services():
    with patch("airpods.cli.commands.backup.resolve_services") as mock:
        spec_webui = MagicMock()
        spec_webui.container = "open-webui-0"
        spec_webui.image = "ghcr.io/open-webui/open-webui:latest"
        spec_webui.name = "open-webui"
        spec_ollama = MagicMock()
        spec_ollama.container = "ollama-0"
        spec_ollama.image = "docker.io/ollama/ollama:latest"
        spec_ollama.name = "ollama"
        mock.side_effect = lambda names: [
            spec_webui if n == "open-webui" else spec_ollama for n in names
        ]
        yield mock


@pytest.fixture
def mock_run_runtime_exec():
    with patch("airpods.cli.commands.backup._run_runtime_exec") as mock:
        mock.return_value.stdout = json.dumps({"models": []})
        yield mock


def _create_dummy_backup(home: Path) -> Path:
    backup_root = home / "archive"
    (backup_root / "configs").mkdir(parents=True)
    (backup_root / "webui").mkdir(parents=True)
    with sqlite3.connect(backup_root / "webui" / "webui.db") as db:
        db.execute("CREATE TABLE example(value TEXT)")
    manifest = backup_root / "manifest.json"
    manifest.write_text(json.dumps({"airpods_version": "test"}), encoding="utf-8")

    archive_path = home / "test-backup.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(backup_root, arcname="airpods_backup")
    return archive_path


def test_backup_creates_archive(
    runner, mock_state_dirs, mock_podman, mock_run_runtime_exec, mock_services
):
    configs = mock_state_dirs["configs"]
    volumes = mock_state_dirs["volumes"]
    (configs / "config.toml").write_text("[cli]\nlog_lines=200\n")
    (volumes / "airpods_webui_data").mkdir()
    with sqlite3.connect(volumes / "airpods_webui_data" / "webui.db") as db:
        db.execute("CREATE TABLE example(value TEXT)")
    (volumes / "webui_plugins").mkdir()

    result = runner.invoke(
        app, ["state", "backup", "--dest", str(mock_state_dirs["home"])]
    )

    assert result.exit_code == 0
    archives = list(mock_state_dirs["home"].glob("*.tar.gz"))
    assert archives


def test_restore_without_archive_shows_help(runner, mock_podman):
    result = runner.invoke(app, ["state", "restore"])
    combined = result.stdout or ""
    assert result.exit_code != 0
    assert "Missing argument" in combined or "ARCHIVE" in combined
    # Should suggest --help, not print full help
    assert "Try 'airpods state restore --help' for more information" in combined
    assert "Restore configs, DB, and metadata" not in combined


def test_restore_missing_archive_errors(runner, mock_podman):
    result = runner.invoke(app, ["state", "restore", "missing.tar.gz"])
    assert result.exit_code != 0
    assert "not found" in result.stdout.lower()


def test_restore_successful(runner, mock_state_dirs, mock_podman):
    archive = _create_dummy_backup(mock_state_dirs["home"])
    with patch(
        "airpods.cli.commands.backup.manager.runtime.container_inspect",
        return_value=None,
    ):
        result = runner.invoke(app, ["state", "restore", str(archive), "--skip-models"])

    assert result.exit_code == 0
    restored_db = mock_state_dirs["volumes"] / "airpods_webui_data" / "webui.db"
    assert restored_db.exists()


def test_extract_archive_rejects_path_traversal(tmp_path):
    archive = tmp_path / "escape.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo(name="../evil.txt")
        data = b"evil"
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

    from airpods.cli.commands import backup as backup_cmds

    with pytest.raises(backup_cmds.RestoreError):
        backup_cmds._extract_archive(archive, tmp_path / "dest")
