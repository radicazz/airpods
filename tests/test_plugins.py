from __future__ import annotations

import base64
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

from airpods import plugins


def _function_source(class_name: str = "Filter") -> str:
    return f'class {class_name}:\n    """Test plugin."""\n    pass\n'


def _prepare_webui_source(tmp_path: Path, relative: str, content: str) -> Path:
    source = tmp_path / "plugins" / "open-webui" / relative
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(content, encoding="utf-8")
    return source


def test_sync_plugins_uses_hash_manifest_and_preserves_user_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _prepare_webui_source(tmp_path, "filters/alpha.py", _function_source())
    target_root = tmp_path / "state" / "volumes"
    target_dir = target_root / "webui_plugins"
    target_dir.mkdir(parents=True)
    (target_dir / "custom.py").write_text("class Filter: pass\n", encoding="utf-8")
    monkeypatch.setattr(plugins, "detect_repo_root", lambda _start=None: tmp_path)
    monkeypatch.setattr(plugins, "volumes_dir", lambda: target_root)

    assert plugins.sync_plugins() == 1
    copied = target_dir / "filters" / "alpha.py"
    assert copied.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert plugins.sync_plugins() == 0

    copied.write_text("locally edited\n", encoding="utf-8")
    copied.touch()
    assert plugins.sync_plugins() == 1
    assert copied.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert (target_dir / "custom.py").exists()
    manifest = json.loads(
        (target_dir / plugins.PLUGIN_MANIFEST_NAME).read_text(encoding="utf-8")
    )
    assert manifest["version"] == 1
    assert set(manifest["files"]) == {"filters/alpha.py"}
    assert plugins.managed_plugin_paths(target_dir) == {Path("filters/alpha.py")}


def test_sync_plugins_prunes_only_previously_managed_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _prepare_webui_source(tmp_path, "filters/alpha.py", _function_source())
    target_root = tmp_path / "state" / "volumes"
    monkeypatch.setattr(plugins, "detect_repo_root", lambda _start=None: tmp_path)
    monkeypatch.setattr(plugins, "volumes_dir", lambda: target_root)
    plugins.sync_plugins()

    target = target_root / "webui_plugins"
    (target / "custom.py").write_text("class Filter: pass\n", encoding="utf-8")
    source.unlink()
    assert plugins.sync_plugins(prune=True) == 0
    assert not (target / "filters" / "alpha.py").exists()
    assert (target / "custom.py").exists()


def test_invalid_manifest_is_ignored_without_pruning_user_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _prepare_webui_source(tmp_path, "filters/alpha.py", _function_source())
    target_root = tmp_path / "state" / "volumes"
    target = target_root / "webui_plugins"
    target.mkdir(parents=True)
    (target / plugins.PLUGIN_MANIFEST_NAME).write_text("not json", encoding="utf-8")
    (target / "custom.py").write_text("class Filter: pass\n", encoding="utf-8")
    monkeypatch.setattr(plugins, "detect_repo_root", lambda _start=None: tmp_path)
    monkeypatch.setattr(plugins, "volumes_dir", lambda: target_root)

    plugins.sync_plugins(prune=True)

    assert (target / "custom.py").exists()
    assert plugins.managed_plugin_paths(target) == {Path("filters/alpha.py")}


def test_discovery_uses_ast_current_classes_and_identifier_safe_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "plugins" / "open-webui"
    _prepare_webui_source(
        tmp_path,
        "filters/my-filter.py",
        dedent(
            '''
            """
            title: Useful Filter
            description: A useful test filter.
            """
            class Filter:
                pass
            ''',
        ),
    )
    _prepare_webui_source(tmp_path, "pipes/echo.py", _function_source("Pipe"))
    _prepare_webui_source(tmp_path, "tools/tool.py", _function_source("Tools"))
    _prepare_webui_source(tmp_path, "not_a_filter.py", 'TEXT = "class Filter:"\n')
    monkeypatch.setattr(plugins, "detect_repo_root", lambda _start=None: tmp_path)

    assert plugins.list_available_plugins() == [
        "airpods_filters_my_filter",
        "airpods_pipes_echo",
    ]
    modules = plugins._discover_function_plugins(source)
    by_id = {module.id: module for module in modules}
    assert by_id["airpods_filters_my_filter"].legacy_id == "filters.my-filter"
    assert by_id["airpods_filters_my_filter"].name == "Useful Filter"
    assert by_id["airpods_pipes_echo"].function_type == "pipe"


class _DummyResult:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_import_uses_parameter_payload_and_managed_allowlist(tmp_path: Path) -> None:
    plugin = tmp_path / "filters" / "gamma.py"
    plugin.parent.mkdir()
    plugin.write_text(_function_source(), encoding="utf-8")
    (tmp_path / "user.py").write_text(_function_source(), encoding="utf-8")
    calls: list[tuple[str, list[str], dict]] = []

    class Runtime:
        def exec_in_container(self, container, command, **kwargs):  # type: ignore[no-untyped-def]
            calls.append((container, command, kwargs))
            return _DummyResult(stdout=json.dumps({"status": "created", "id": "x"}))

    result = plugins.import_plugins_to_webui(
        Runtime(),
        tmp_path,
        admin_user_id="owner",
        container_name="custom-container",
        managed_paths={Path("filters/gamma.py")},
    )

    assert result.created == 1
    assert result.succeeded == 1
    assert result.modules[0].id == "airpods_filters_gamma"
    container, command, kwargs = calls[0]
    assert container == "custom-container"
    assert command[:2] == ["python3", "-c"]
    payload = json.loads(base64.b64decode(command[3]))
    assert payload["user_id"] == "owner"
    assert payload["id"] == "airpods_filters_gamma"
    assert payload["legacy_id"] == "filters.gamma"
    assert payload["meta"]["airpods_managed"] is True
    assert kwargs["check"] is False


@pytest.mark.parametrize("failure", ["lock", "timeout"])
def test_import_retries_transient_database_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    plugin = tmp_path / "gamma.py"
    plugin.write_text(_function_source(), encoding="utf-8")
    sleeps: list[float] = []
    monkeypatch.setattr(plugins.time, "sleep", sleeps.append)

    class Runtime:
        calls = 0

        def exec_in_container(self, container, command, **kwargs):  # type: ignore[no-untyped-def]
            self.calls += 1
            if self.calls == 1:
                if failure == "timeout":
                    raise subprocess.TimeoutExpired(command, kwargs["timeout"])
                return _DummyResult(
                    returncode=1,
                    stderr="sqlite3.OperationalError: database is locked",
                )
            return _DummyResult(stdout=json.dumps({"status": "updated", "id": "x"}))

    runtime = Runtime()
    result = plugins.import_plugins_to_webui(
        runtime, tmp_path, managed_paths={Path("gamma.py")}
    )

    assert result.updated == 1
    assert runtime.calls == 2
    assert sleeps == [plugins.SQLITE_IMPORT_INITIAL_RETRY_DELAY]


def _create_webui_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE function (
            id TEXT PRIMARY KEY, user_id TEXT, name TEXT, type TEXT, content TEXT,
            meta TEXT, created_at INTEGER, updated_at INTEGER,
            is_active INTEGER, is_global INTEGER
        );
        CREATE TABLE function_history (id TEXT PRIMARY KEY, function_id TEXT);
        CREATE TABLE user (id TEXT PRIMARY KEY, settings TEXT);
        CREATE TABLE model (id TEXT PRIMARY KEY, meta TEXT);
        """
    )
    connection.execute(
        "INSERT INTO function VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "filters.gamma",
            "old-owner",
            "Old name",
            "filter",
            "old content",
            json.dumps({"valves": {"limit": 3}, "custom": True}),
            10,
            20,
            0,
            1,
        ),
    )
    connection.execute("INSERT INTO function_history VALUES ('h1', 'filters.gamma')")
    connection.execute(
        "INSERT INTO user VALUES (?, ?)",
        ("u1", json.dumps({"functions": {"valves": {"filters.gamma": {"x": 1}}}})),
    )
    connection.execute(
        "INSERT INTO model VALUES (?, ?)",
        ("m1", json.dumps({"filterIds": ["filters.gamma"]})),
    )
    connection.commit()
    connection.close()


def test_import_script_migrates_legacy_id_and_preserves_open_webui_state(
    tmp_path: Path,
) -> None:
    database = tmp_path / "webui.db"
    _create_webui_database(database)
    payload = {
        "id": "airpods_filters_gamma",
        "legacy_id": "filters.gamma",
        "user_id": "new-owner",
        "name": "Gamma",
        "type": "filter",
        "content": "new content",
        "meta": {"description": "Managed", "airpods_managed": True},
    }
    script = plugins._IMPORT_PLUGIN_SCRIPT.replace(
        'DB_PATH = "/app/backend/data/webui.db"', f"DB_PATH = {str(database)!r}"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            base64.b64encode(json.dumps(payload).encode()).decode(),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(result.stdout)["status"] == "migrated"

    connection = sqlite3.connect(database)
    row = connection.execute(
        "SELECT id, user_id, content, meta, created_at, is_active, is_global FROM function"
    ).fetchone()
    assert row is not None
    assert row[:3] == ("airpods_filters_gamma", "new-owner", "new content")
    assert json.loads(row[3])["valves"] == {"limit": 3}
    assert json.loads(row[3])["custom"] is True
    assert row[4:] == (10, 0, 1)
    assert connection.execute(
        "SELECT function_id FROM function_history"
    ).fetchone() == ("airpods_filters_gamma",)
    settings = json.loads(connection.execute("SELECT settings FROM user").fetchone()[0])
    model_meta = json.loads(connection.execute("SELECT meta FROM model").fetchone()[0])
    connection.close()
    assert "airpods_filters_gamma" in settings["functions"]["valves"]
    assert model_meta["filterIds"] == ["airpods_filters_gamma"]


def test_import_script_refuses_canonical_legacy_collision(tmp_path: Path) -> None:
    database = tmp_path / "webui.db"
    _create_webui_database(database)
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO function VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("airpods_filters_gamma", "u", "n", "filter", "c", "{}", 1, 1, 1, 0),
    )
    connection.commit()
    connection.close()
    payload = {
        "id": "airpods_filters_gamma",
        "legacy_id": "filters.gamma",
        "user_id": "u",
        "name": "Gamma",
        "type": "filter",
        "content": "new",
        "meta": {},
    }
    script = plugins._IMPORT_PLUGIN_SCRIPT.replace(
        'DB_PATH = "/app/backend/data/webui.db"', f"DB_PATH = {str(database)!r}"
    )

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            base64.b64encode(json.dumps(payload).encode()).decode(),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "both canonical and legacy function IDs exist" in result.stderr


def test_resolve_plugin_owner_auto_prefers_admin() -> None:
    calls = 0

    class Runtime:
        def exec_in_container(self, container, command, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal calls
            calls += 1
            return _DummyResult(stdout="admin-user\n")

    assert (
        plugins.resolve_plugin_owner_user_id(Runtime(), "open-webui-0") == "admin-user"
    )
    assert calls == 1


@pytest.mark.parametrize("mode", ["auto", "admin", "airpods"])
def test_resolve_plugin_owner_never_creates_accounts(mode: str) -> None:
    calls = 0

    class Runtime:
        def exec_in_container(self, container, command, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal calls
            calls += 1
            return _DummyResult(stdout="")

    assert (
        plugins.resolve_plugin_owner_user_id(Runtime(), "open-webui-0", mode)
        == "system"
    )
    assert calls == (0 if mode == "airpods" else 1)


def test_sync_comfyui_plugins_copies_directories(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_dir = tmp_path / "plugins" / "comfyui" / "custom_nodes"
    package = source_dir / "custom_node_a"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("# package", encoding="utf-8")
    (source_dir / "simple_node.py").write_text("# file", encoding="utf-8")
    target_root = tmp_path / "state" / "volumes"
    monkeypatch.setattr(plugins, "detect_repo_root", lambda _start=None: tmp_path)
    monkeypatch.setattr(plugins, "volumes_dir", lambda: target_root)

    assert plugins.sync_comfyui_plugins(force=True, prune=False) == 2
    assert (target_root / "comfyui_custom_nodes" / "custom_node_a").exists()
    assert (target_root / "comfyui_custom_nodes" / "simple_node.py").exists()


def test_sync_comfyui_plugins_prunes_removed_items(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_dir = tmp_path / "plugins" / "comfyui" / "custom_nodes"
    package = source_dir / "current"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("# package", encoding="utf-8")
    target_root = tmp_path / "state" / "volumes"
    target = target_root / "comfyui_custom_nodes"
    old = target / "old"
    old.mkdir(parents=True)
    (old / "__init__.py").write_text("# old", encoding="utf-8")
    (target / "legacy.py").write_text("# old", encoding="utf-8")
    monkeypatch.setattr(plugins, "detect_repo_root", lambda _start=None: tmp_path)
    monkeypatch.setattr(plugins, "volumes_dir", lambda: target_root)

    plugins.sync_comfyui_plugins(force=True, prune=True)

    assert (target / "current").exists()
    assert not old.exists()
    assert not (target / "legacy.py").exists()


def test_sync_comfyui_plugins_skips_non_package_dirs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_dir = tmp_path / "plugins" / "comfyui" / "custom_nodes"
    non_package = source_dir / "not_a_package"
    non_package.mkdir(parents=True)
    (non_package / "readme.txt").write_text("Docs", encoding="utf-8")
    target_root = tmp_path / "state" / "volumes"
    monkeypatch.setattr(plugins, "detect_repo_root", lambda _start=None: tmp_path)
    monkeypatch.setattr(plugins, "volumes_dir", lambda: target_root)

    assert plugins.sync_comfyui_plugins(force=True, prune=False) == 0
    assert not (target_root / "comfyui_custom_nodes" / "not_a_package").exists()
