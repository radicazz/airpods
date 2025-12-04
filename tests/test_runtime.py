"""Tests for runtime abstraction layer."""

from __future__ import annotations

import pytest

from airpods.runtime import (
    ContainerRuntimeError,
    PodmanRuntime,
    get_runtime,
)


class TestGetRuntime:
    """Test the runtime factory function."""

    def test_get_runtime_none_returns_podman(self):
        """get_runtime(None) should return PodmanRuntime."""
        runtime = get_runtime(None)
        assert isinstance(runtime, PodmanRuntime)

    def test_get_runtime_auto_returns_podman(self):
        """get_runtime('auto') should return PodmanRuntime."""
        runtime = get_runtime("auto")
        assert isinstance(runtime, PodmanRuntime)

    def test_get_runtime_podman_returns_podman(self):
        """get_runtime('podman') should return PodmanRuntime."""
        runtime = get_runtime("podman")
        assert isinstance(runtime, PodmanRuntime)

    def test_get_runtime_docker_raises_error(self):
        """get_runtime('docker') should raise ContainerRuntimeError."""
        with pytest.raises(
            ContainerRuntimeError,
            match="Docker is not supported yet.*podman.*auto",
        ):
            get_runtime("docker")

    def test_get_runtime_unknown_raises_error(self):
        """get_runtime with unknown value should raise ContainerRuntimeError."""
        with pytest.raises(ContainerRuntimeError, match="Unknown runtime 'foobar'"):
            get_runtime("foobar")


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
            "ensure_network",
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
