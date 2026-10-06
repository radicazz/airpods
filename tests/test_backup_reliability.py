"""Regression coverage for backup reliability."""

from __future__ import annotations

import io
import sqlite3
import tarfile
from unittest.mock import MagicMock

import pytest

from airpods.cli.commands import backup


def test_backup_includes_committed_wal_data(tmp_path, monkeypatch):
    volumes = tmp_path / "volumes"
    source = volumes / backup.WEBUI_VOLUME / "webui.db"
    source.parent.mkdir(parents=True)
    staging = tmp_path / "staging"
    staging.mkdir()
    monkeypatch.setattr(backup, "volumes_dir", lambda: volumes)
    with sqlite3.connect(source) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.execute("CREATE TABLE example(value TEXT)")
        db.execute("INSERT INTO example VALUES ('committed')")
        db.commit()
        assert backup._collect_webui_db(staging)
        assert backup._dump_webui_db(None, staging, True, None)
        with sqlite3.connect(staging / backup.BACKUP_PATHS["webui_db"]) as snapshot:
            assert snapshot.execute("SELECT value FROM example").fetchone() == (
                "committed",
            )
        assert "committed" in (staging / backup.BACKUP_PATHS["webui_dump"]).read_text()


def test_failed_database_restore_preserves_existing_file(tmp_path, monkeypatch):
    volumes = tmp_path / "volumes"
    dest = volumes / backup.WEBUI_VOLUME / "webui.db"
    dest.parent.mkdir(parents=True)
    with sqlite3.connect(dest) as db:
        db.execute("CREATE TABLE original(value TEXT)")
    original = dest.read_bytes()
    root = tmp_path / "archive"
    raw = root / backup.BACKUP_PATHS["webui_db"]
    raw.parent.mkdir(parents=True)
    raw.write_text("invalid database")
    monkeypatch.setattr(backup, "volumes_dir", lambda: volumes)
    monkeypatch.setattr(backup, "_assert_webui_stopped", lambda: None)
    with pytest.raises(backup.RestoreError):
        backup._restore_webui_db(root, True)
    assert dest.read_bytes() == original


def test_running_webui_database_restore_is_rejected(monkeypatch):
    manager = MagicMock()
    manager.runtime.container_inspect.return_value = {"State": {"Running": True}}
    monkeypatch.setattr(backup, "manager", manager)
    with pytest.raises(backup.RestoreError, match="Stop Open WebUI"):
        backup._assert_webui_stopped()


@pytest.mark.parametrize(
    "kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.FIFOTYPE]
)
def test_legacy_extraction_rejects_links_and_special_files(tmp_path, kind):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        member = tarfile.TarInfo("airpods_backup/link")
        member.type = kind
        member.linkname = "/tmp/outside"
        archive.addfile(member)
    buffer.seek(0)
    with tarfile.open(fileobj=buffer, mode="r") as archive:
        with pytest.raises(backup.RestoreError):
            backup._safe_extractall(archive, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_legacy_extraction_accepts_regular_backup(tmp_path):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        member = tarfile.TarInfo("airpods_backup/configs/config.toml")
        data = b"[cli]\nlog_lines=100\n"
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))
    buffer.seek(0)
    with tarfile.open(fileobj=buffer, mode="r") as archive:
        backup._safe_extractall(archive, tmp_path)
    assert (tmp_path / "airpods_backup/configs/config.toml").read_bytes() == data
