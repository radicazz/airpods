from __future__ import annotations

import subprocess
from pathlib import Path
from textwrap import dedent

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

    synced = plugins.sync_plugins(force=True, prune=False)

    assert synced == 2
    assert (target_dir / "alpha.py").read_text(encoding="utf-8") == "print('alpha')"
    assert (target_dir / "beta.py").exists()
    # User files should be preserved
    assert (target_dir / "legacy.py").exists()


def test_import_functions_uses_container(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plugin_dir = tmp_path
    (plugin_dir / "gamma.py").write_text(
        dedent(
            """
            class Filter:
                def inlet(self, body, __user__=None):
                    return body
            """
        ),
        encoding="utf-8",
    )
    (plugin_dir / "tools" / "gamma_tool.py").parent.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "tools" / "gamma_tool.py").write_text(
        "class Tools:\n    pass\n", encoding="utf-8"
    )

    captured: dict[str, list[str]] = {}
    calls: list[list[str]] = []

    class DummyResult:
        returncode = 0
        stdout = "Imported gamma: 1"
        stderr = ""

    class MockRuntime:
        def exec_in_container(self, container, cmd, **kwargs):  # type: ignore[no-untyped-def]
            import subprocess

            # Build the command as runtime would
            full_cmd = ["podman", "exec", container] + cmd
            captured["cmd"] = full_cmd
            calls.append(full_cmd)
            return DummyResult()

    mock_runtime = MockRuntime()

    imported = plugins.import_plugins_to_webui(
        mock_runtime,
        plugin_dir,
        admin_user_id="owner",
        container_name="custom-container",
    )

    assert len(imported) == 1
    assert imported[0].id == "gamma"
    assert captured["cmd"][2] == "custom-container"
    assert "user_id = excluded.user_id" in captured["cmd"][-1]
    assert len(calls) == 1


def test_import_functions_retries_when_database_locked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plugin_dir = tmp_path
    (plugin_dir / "gamma.py").write_text(
        dedent(
            """
            class Filter:
                def inlet(self, body, __user__=None):
                    return body
            """
        ),
        encoding="utf-8",
    )

    sleeps: list[float] = []
    monkeypatch.setattr(plugins.time, "sleep", lambda seconds: sleeps.append(seconds))

    calls: list[dict[str, object]] = []

    class DummyResult:
        def __init__(
            self,
            *,
            returncode: int,
            stdout: str = "",
            stderr: str = "",
        ) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    class MockRuntime:
        def exec_in_container(self, container, cmd, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(kwargs)
            if len(calls) == 1:
                return DummyResult(
                    returncode=1,
                    stdout=(
                        "Traceback (most recent call last):\n"
                        "sqlite3.OperationalError: database is locked"
                    ),
                )
            return DummyResult(returncode=0, stdout="Imported gamma: 1")

    imported = plugins.import_plugins_to_webui(
        MockRuntime(),
        plugin_dir,
        admin_user_id="owner",
        container_name="custom-container",
    )

    assert len(imported) == 1
    assert len(calls) == 2
    assert calls[0]["check"] is False
    assert sleeps == [plugins.SQLITE_IMPORT_INITIAL_RETRY_DELAY]


def test_import_functions_retries_when_exec_times_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plugin_dir = tmp_path
    (plugin_dir / "gamma.py").write_text(
        dedent(
            """
            class Filter:
                def inlet(self, body, __user__=None):
                    return body
            """
        ),
        encoding="utf-8",
    )

    sleeps: list[float] = []
    monkeypatch.setattr(plugins.time, "sleep", lambda seconds: sleeps.append(seconds))

    calls: list[dict[str, object]] = []

    class DummyResult:
        def __init__(
            self,
            *,
            returncode: int,
            stdout: str = "",
            stderr: str = "",
        ) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    class MockRuntime:
        def exec_in_container(self, container, cmd, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(kwargs)
            if len(calls) == 1:
                raise subprocess.TimeoutExpired(
                    cmd=cmd,
                    timeout=plugins.SQLITE_IMPORT_EXEC_TIMEOUT_SECONDS,
                )
            return DummyResult(returncode=0, stdout="Imported gamma: 1")

    imported = plugins.import_plugins_to_webui(
        MockRuntime(),
        plugin_dir,
        admin_user_id="owner",
        container_name="custom-container",
    )

    assert len(imported) == 1
    assert len(calls) == 2
    assert calls[0]["check"] is False
    assert sleeps == [plugins.SQLITE_IMPORT_INITIAL_RETRY_DELAY]


def test_list_available_plugins_discovers_nested_filters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_dir = tmp_path / "plugins" / "open-webui"
    (source_dir / "filters").mkdir(parents=True)
    (source_dir / "filters" / "alpha.py").write_text(
        "class Filter:\n    pass\n", encoding="utf-8"
    )
    (source_dir / "tools").mkdir(parents=True)
    (source_dir / "tools" / "tool.py").write_text(
        "class Tools:\n    pass\n", encoding="utf-8"
    )

    monkeypatch.setattr(plugins, "detect_repo_root", lambda _start=None: tmp_path)

    assert plugins.list_available_plugins() == ["filters.alpha"]


def test_list_installed_plugins_discovers_nested_filters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target_root = tmp_path / "state" / "volumes"
    plugin_dir = target_root / "webui_plugins" / "filters"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "omega.py").write_text("class Filter:\n    pass\n", encoding="utf-8")
    tools_dir = target_root / "webui_plugins" / "tools"
    tools_dir.mkdir(parents=True)
    (tools_dir / "tool.py").write_text("class Tools:\n    pass\n", encoding="utf-8")

    monkeypatch.setattr(plugins, "volumes_dir", lambda: target_root)

    assert plugins.list_installed_plugins() == ["filters.omega"]


def test_resolve_plugin_owner_auto_prefers_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    class DummyResult:
        returncode = 0
        stderr = ""

        def __init__(self, stdout: str):
            self.stdout = stdout

    outputs = ["admin-user\n"]

    class MockRuntime:
        def exec_in_container(self, container, cmd, **kwargs):  # type: ignore[no-untyped-def]
            full_cmd = ["podman", "exec", container] + cmd
            calls.append(full_cmd)
            return DummyResult(outputs.pop(0) if outputs else "")

    mock_runtime = MockRuntime()

    owner = plugins.resolve_plugin_owner_user_id(
        mock_runtime, "open-webui-0", mode="auto"
    )
    assert owner == "admin-user"
    assert len(calls) == 1


def test_resolve_plugin_owner_auto_creates_default_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DummyResult:
        returncode = 0
        stderr = ""

        def __init__(self, stdout: str):
            self.stdout = stdout

    # Outputs: no existing admin, no users exist, create default admin
    outputs = ["", "", "test-admin-id\n"]

    class MockRuntime:
        def exec_in_container(self, container, cmd, **kwargs):  # type: ignore[no-untyped-def]
            return DummyResult(outputs.pop(0) if outputs else "")

    mock_runtime = MockRuntime()

    owner = plugins.resolve_plugin_owner_user_id(
        mock_runtime, "open-webui-0", mode="auto"
    )
    assert owner == "test-admin-id"


def test_resolve_plugin_owner_admin_mode_uses_system_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DummyResult:
        returncode = 0
        stderr = ""

        def __init__(self, stdout: str):
            self.stdout = stdout

    outputs = [""]

    class MockRuntime:
        def exec_in_container(self, container, cmd, **kwargs):  # type: ignore[no-untyped-def]
            return DummyResult(outputs.pop(0) if outputs else "")

    mock_runtime = MockRuntime()

    owner = plugins.resolve_plugin_owner_user_id(
        mock_runtime, "open-webui-0", mode="admin"
    )
    assert owner == "system"


def test_sync_comfyui_plugins_copies_directories(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_dir = tmp_path / "plugins" / "comfyui" / "custom_nodes"
    source_dir.mkdir(parents=True)

    # Create a directory-based custom node (package with __init__.py)
    (source_dir / "custom_node_a").mkdir()
    (source_dir / "custom_node_a" / "__init__.py").write_text(
        "# Custom node A", encoding="utf-8"
    )
    (source_dir / "custom_node_a" / "node.py").write_text(
        "# Node implementation", encoding="utf-8"
    )

    # Create a single-file custom node
    (source_dir / "simple_node.py").write_text("# Simple node", encoding="utf-8")

    target_root = tmp_path / "state" / "volumes"
    target_dir = target_root / "comfyui_custom_nodes"

    monkeypatch.setattr(plugins, "detect_repo_root", lambda _start=None: tmp_path)
    monkeypatch.setattr(plugins, "volumes_dir", lambda: target_root)

    synced = plugins.sync_comfyui_plugins(force=True, prune=False)

    assert synced == 2
    assert (target_dir / "custom_node_a" / "__init__.py").exists()
    assert (target_dir / "custom_node_a" / "node.py").exists()
    assert (target_dir / "simple_node.py").exists()


def test_sync_comfyui_plugins_prunes_removed_items(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_dir = tmp_path / "plugins" / "comfyui" / "custom_nodes"
    source_dir.mkdir(parents=True)

    # Create one custom node in source
    (source_dir / "custom_node_a").mkdir()
    (source_dir / "custom_node_a" / "__init__.py").write_text(
        "# Custom node A", encoding="utf-8"
    )

    target_root = tmp_path / "state" / "volumes"
    target_dir = target_root / "comfyui_custom_nodes"
    target_dir.mkdir(parents=True)

    # Create legacy items in target that don't exist in source
    (target_dir / "old_node").mkdir()
    (target_dir / "old_node" / "__init__.py").write_text("# Old", encoding="utf-8")
    (target_dir / "legacy.py").write_text("# Legacy", encoding="utf-8")

    monkeypatch.setattr(plugins, "detect_repo_root", lambda _start=None: tmp_path)
    monkeypatch.setattr(plugins, "volumes_dir", lambda: target_root)

    synced = plugins.sync_comfyui_plugins(force=True, prune=True)

    assert synced == 1
    assert (target_dir / "custom_node_a").exists()
    assert not (target_dir / "old_node").exists()
    assert not (target_dir / "legacy.py").exists()


def test_sync_comfyui_plugins_skips_non_package_dirs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_dir = tmp_path / "plugins" / "comfyui" / "custom_nodes"
    source_dir.mkdir(parents=True)

    # Create a directory without __init__.py (not a package)
    (source_dir / "not_a_package").mkdir()
    (source_dir / "not_a_package" / "readme.txt").write_text("Docs", encoding="utf-8")

    target_root = tmp_path / "state" / "volumes"

    monkeypatch.setattr(plugins, "detect_repo_root", lambda _start=None: tmp_path)
    monkeypatch.setattr(plugins, "volumes_dir", lambda: target_root)

    synced = plugins.sync_comfyui_plugins(force=True, prune=False)

    assert synced == 0
    assert not (target_root / "comfyui_custom_nodes" / "not_a_package").exists()


def test_import_plugins_to_webui_returns_list_of_modules(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from textwrap import dedent

    plugin_dir = tmp_path
    (plugin_dir / "myfilter.py").write_text(
        dedent("""
        class Filter:
            def inlet(self, body, __user__=None):
                return body
        """),
        encoding="utf-8",
    )

    class DummyResult:
        returncode = 0
        stdout = "Imported myfilter: 1"
        stderr = ""

    class MockRuntime:
        def exec_in_container(self, container, cmd, **kwargs):  # type: ignore[no-untyped-def]
            return DummyResult()

    result = plugins.import_plugins_to_webui(
        MockRuntime(), plugin_dir, admin_user_id="owner", container_name="test"
    )

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].id == "myfilter"
    assert result[0].function_type == "filter"


def test_webui_signin_returns_token_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MockResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"token": "abc123"}

    calls: list[dict] = []

    def mock_post(
        url: str, json: dict | None = None, timeout: object = None, **kwargs: object
    ) -> MockResponse:
        calls.append({"url": url, "json": json})
        return MockResponse()

    monkeypatch.setattr(plugins.requests, "post", mock_post)

    token = plugins._webui_signin("http://localhost:3000", "admin@airpods", "admin")

    assert token == "abc123"
    assert len(calls) == 1
    assert calls[0]["url"] == "http://localhost:3000/api/v1/auths/signin"
    assert calls[0]["json"] == {"email": "admin@airpods", "password": "admin"}


def test_webui_signin_returns_none_on_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def mock_post(url: str, **kwargs: object) -> None:
        raise plugins.requests.ConnectionError("refused")

    monkeypatch.setattr(plugins.requests, "post", mock_post)

    token = plugins._webui_signin("http://localhost:3000", "admin@airpods", "admin")
    assert token is None


def test_webui_signin_returns_none_on_bad_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MockResponse:
        status_code = 401

        def raise_for_status(self) -> None:
            raise plugins.requests.HTTPError(response=self)  # type: ignore[arg-type]

        def json(self) -> dict:
            return {"detail": "Unauthorized"}

    monkeypatch.setattr(plugins.requests, "post", lambda *a, **kw: MockResponse())

    token = plugins._webui_signin("http://localhost:3000", "user@x", "wrongpass")
    assert token is None


def test_reload_functions_via_api_calls_update_endpoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = plugins.PluginModule(
        id="filters.alpha",
        path=tmp_path / "filters" / "alpha.py",
        content="class Filter:\n    def inlet(self, body): return body\n",
        function_type="filter",
    )

    calls: list[dict] = []

    class MockResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"id": "filters.alpha"}

    def mock_post(
        url: str,
        json: dict | None = None,
        headers: dict | None = None,
        timeout: object = None,
        **kwargs: object,
    ) -> MockResponse:
        calls.append({"url": url, "json": json, "headers": headers})
        return MockResponse()

    monkeypatch.setattr(plugins.requests, "post", mock_post)

    reloaded = plugins.reload_functions_via_api(
        "http://localhost:3000", "tok123", [module]
    )

    assert reloaded == 1
    assert len(calls) == 1
    assert (
        calls[0]["url"]
        == "http://localhost:3000/api/v1/functions/id/filters.alpha/update"
    )
    assert calls[0]["json"] == {"id": "filters.alpha", "content": module.content}
    assert calls[0]["headers"] == {"Authorization": "Bearer tok123"}


def test_reload_functions_via_api_skips_on_http_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    modules = [
        plugins.PluginModule(
            "a",
            tmp_path / "a.py",
            "class Filter:\n    def inlet(self, b): return b\n",
            "filter",
        ),
        plugins.PluginModule(
            "b",
            tmp_path / "b.py",
            "class Filter:\n    def inlet(self, b): return b\n",
            "filter",
        ),
    ]

    call_count = 0

    class MockFailResponse:
        status_code = 500

        def raise_for_status(self) -> None:
            raise plugins.requests.HTTPError()

    class MockOkResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

    def mock_post(url: str, **kwargs: object) -> MockFailResponse | MockOkResponse:
        nonlocal call_count
        call_count += 1
        return MockFailResponse() if call_count == 1 else MockOkResponse()

    monkeypatch.setattr(plugins.requests, "post", mock_post)

    reloaded = plugins.reload_functions_via_api("http://localhost:3000", "tok", modules)

    assert reloaded == 1
    assert call_count == 2
