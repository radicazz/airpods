"""Tests for runtime abstraction layer."""

from __future__ import annotations

import pytest

from airpods.runtime import (
    ContainerRuntimeError,
    DockerRuntime,
    PodmanRuntime,
    get_runtime,
)


class TestGetRuntime:
    """Test the runtime factory function."""

    def test_get_runtime_none_auto_detects(self, monkeypatch):
        """get_runtime(None) should auto-detect available runtime."""

        # Mock shutil.which to simulate podman being available
        def mock_which(cmd):
            return "/usr/bin/podman" if cmd == "podman" else None

        monkeypatch.setattr("shutil.which", mock_which)
        runtime = get_runtime(None)
        assert isinstance(runtime, PodmanRuntime)

    def test_get_runtime_auto_prefers_podman(self, monkeypatch):
        """get_runtime('auto') should prefer podman when both are available."""

        # Mock both runtimes as available
        def mock_which(cmd):
            return f"/usr/bin/{cmd}" if cmd in ("podman", "docker") else None

        monkeypatch.setattr("shutil.which", mock_which)
        runtime = get_runtime("auto")
        assert isinstance(runtime, PodmanRuntime)

    def test_get_runtime_auto_falls_back_to_docker(self, monkeypatch):
        """get_runtime('auto') should use docker if podman not available."""

        # Mock only docker as available
        def mock_which(cmd):
            return "/usr/bin/docker" if cmd == "docker" else None

        monkeypatch.setattr("shutil.which", mock_which)
        runtime = get_runtime("auto")
        assert isinstance(runtime, DockerRuntime)

    def test_get_runtime_auto_raises_if_none_available(self, monkeypatch):
        """get_runtime('auto') should raise error if neither runtime available."""
        # Mock no runtimes available
        monkeypatch.setattr("shutil.which", lambda cmd: None)
        with pytest.raises(
            ContainerRuntimeError,
            match="No container runtime found. Please install either Podman or Docker.",
        ):
            get_runtime("auto")

    def test_get_runtime_podman_returns_podman(self, monkeypatch):
        """get_runtime('podman') should return PodmanRuntime."""
        monkeypatch.setattr(
            "shutil.which", lambda cmd: "/usr/bin/podman" if cmd == "podman" else None
        )
        runtime = get_runtime("podman")
        assert isinstance(runtime, PodmanRuntime)

    def test_get_runtime_docker_returns_docker(self, monkeypatch):
        """get_runtime('docker') should return DockerRuntime."""
        monkeypatch.setattr(
            "shutil.which", lambda cmd: "/usr/bin/docker" if cmd == "docker" else None
        )
        runtime = get_runtime("docker")
        assert isinstance(runtime, DockerRuntime)

    def test_get_runtime_podman_raises_if_unavailable(self, monkeypatch):
        """get_runtime('podman') should fail fast if podman is unavailable."""
        monkeypatch.setattr("shutil.which", lambda cmd: None)
        with pytest.raises(
            ContainerRuntimeError,
            match="Runtime preference is set to 'podman' but Podman is not installed.",
        ):
            get_runtime("podman")

    def test_get_runtime_docker_raises_if_unavailable(self, monkeypatch):
        """get_runtime('docker') should fail fast if docker is unavailable."""
        monkeypatch.setattr("shutil.which", lambda cmd: None)
        with pytest.raises(
            ContainerRuntimeError,
            match="Runtime preference is set to 'docker' but Docker is not installed.",
        ):
            get_runtime("docker")

    def test_get_runtime_unknown_raises_error(self):
        """get_runtime with unknown value should raise ContainerRuntimeError."""
        with pytest.raises(ContainerRuntimeError, match="Unknown runtime 'foobar'"):
            get_runtime("foobar")

    def test_runtime_name_property(self, monkeypatch):
        """Test runtime_name property returns correct values."""
        monkeypatch.setattr(
            "shutil.which",
            lambda cmd: f"/usr/bin/{cmd}" if cmd in ("podman", "docker") else None,
        )
        podman_runtime = get_runtime("podman")
        assert podman_runtime.runtime_name == "podman"

        docker_runtime = get_runtime("docker")
        assert docker_runtime.runtime_name == "docker"


class TestPodmanRuntime:
    """Test the PodmanRuntime implementation."""

    def test_podman_runtime_instantiates(self):
        """PodmanRuntime should instantiate without errors."""
        runtime = PodmanRuntime()
        assert runtime is not None

    def test_podman_runtime_has_required_methods(self):
        """PodmanRuntime should have all required protocol methods."""
        runtime = PodmanRuntime()
        required_methods = [
            "ensure_volume",
            "pull_image",
            "ensure_pod",
            "run_container",
            "container_exists",
            "pod_exists",
            "stop_pod",
            "remove_pod",
            "pod_status",
            "pod_inspect",
            "stream_logs",
            "exec_in_container",
            "copy_to_container",
            "copy_from_container",
            "container_inspect",
            "list_containers",
        ]
        for method in required_methods:
            assert hasattr(runtime, method), f"Missing method: {method}"
            assert callable(getattr(runtime, method))


class TestDockerRuntime:
    """Test the DockerRuntime implementation."""

    def test_docker_runtime_instantiates(self):
        """DockerRuntime should instantiate without errors."""
        runtime = DockerRuntime()
        assert runtime is not None

    def test_docker_runtime_has_required_methods(self):
        """DockerRuntime should have all required protocol methods."""
        runtime = DockerRuntime()
        required_methods = [
            "ensure_volume",
            "pull_image",
            "ensure_pod",
            "run_container",
            "container_exists",
            "pod_exists",
            "stop_pod",
            "remove_pod",
            "pod_status",
            "pod_inspect",
            "stream_logs",
            "exec_in_container",
            "copy_to_container",
            "copy_from_container",
            "container_inspect",
            "list_containers",
        ]
        for method in required_methods:
            assert hasattr(runtime, method), f"Missing method: {method}"
            assert callable(getattr(runtime, method))


class TestContainerRuntimeError:
    """Test the ContainerRuntimeError exception."""

    def test_container_runtime_error_is_runtime_error(self):
        """ContainerRuntimeError should be a subclass of RuntimeError."""
        assert issubclass(ContainerRuntimeError, RuntimeError)

    def test_container_runtime_error_message(self):
        """ContainerRuntimeError should preserve the error message."""
        error = ContainerRuntimeError("test error message")
        assert str(error) == "test error message"
