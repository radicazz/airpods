from __future__ import annotations

from pathlib import Path

import pytest

from airpods import plugins


def test_sync_plugins_copies_and_preserves_user_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_dir = tmp_path / "plugins" / "open-webui"
    source_dir.mkdir(parents=True)
    (source_dir / "alpha.py").write_text("print('alpha')", encoding="utf-8")
    (source_dir / "beta.py").write_text("print('beta')", encoding="utf-8")

    target_root = tmp_path / "state" / "volumes"
    target_dir = target_root / "webui_plugins"
    target_dir.mkdir(parents=True)
    (target_dir / "alpha.py").write_text("old", encoding="utf-8")
    (target_dir / "legacy.py").write_text("legacy", encoding="utf-8")

    monkeypatch.setattr(plugins, "detect_repo_root", lambda _start=None: tmp_path)
    monkeypatch.setattr(plugins, "volumes_dir", lambda: target_root)

    synced = plugins.sync_plugins(force=True)

    assert synced == 2
    assert (target_dir / "alpha.py").read_text(encoding="utf-8") == "print('alpha')"
    assert (target_dir / "beta.py").exists()
    # User files should be preserved
    assert (target_dir / "legacy.py").exists()


def test_import_functions_uses_container(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plugin_dir = tmp_path
    (plugin_dir / "gamma.py").write_text("print('gamma')", encoding="utf-8")

    captured: dict[str, list[str]] = {}

    class DummyResult:
        returncode = 0
        stdout = "Imported gamma: 1"
        stderr = ""

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        captured["cmd"] = cmd
        return DummyResult()

    import subprocess

    monkeypatch.setattr(subprocess, "run", fake_run)

    imported = plugins.import_plugins_to_webui(
        plugin_dir, admin_user_id="owner", container_name="custom-container"
    )

    assert imported == 1
    assert captured["cmd"][2] == "custom-container"
