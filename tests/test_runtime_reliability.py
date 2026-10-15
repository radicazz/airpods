"""Regression coverage for runtime reliability."""

from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

import pytest

from airpods import docker, podman
from airpods.runtime import ContainerRuntimeError, DockerRuntime, PodmanRuntime


@pytest.mark.parametrize(
    ("module", "runtime_cls"), [(docker, DockerRuntime), (podman, PodmanRuntime)]
)
def test_container_inspection_ignores_stderr_warnings(monkeypatch, module, runtime_cls):
    # Exercise the real runner with both streams populated, as Podman does when
    # device discovery emits warnings alongside otherwise valid inspection JSON.
    monkeypatch.setattr(
        module._cli,
        "_cmd",
        [
            sys.executable,
            "-c",
            "import sys; "
            "print('warning: permission denied for /dev/vboxusb', file=sys.stderr); "
            'print(\'[{"State": {"Status": "running"}}]\')',
        ],
    )
    assert runtime_cls().container_inspect("llamacpp-0") == {
        "State": {"Status": "running"}
    }


def test_docker_operations_only_target_configured_members(monkeypatch):
    runtime = DockerRuntime({"ollama": ["custom-ai-server"]})
    calls = []
    monkeypatch.setattr(docker, "container_exists", lambda name: True)
    monkeypatch.setattr(docker, "_run", lambda args, **kwargs: calls.append(args))
    runtime.stop_pod("ollama")
    runtime.remove_pod("ollama")
    assert [call[-1] for call in calls] == ["custom-ai-server", "custom-ai-server"]
    monkeypatch.setattr(
        docker,
        "_ps_json",
        lambda: [
            {"Names": name, "State": "running"}
            for name in ("custom-ai-server", "other-ollama-0", "ollama-extra-0")
        ],
    )
    assert runtime.pod_status() == [
        {
            "Name": "ollama",
            "Status": "Running",
            "Containers": [{"Names": "custom-ai-server", "Status": "Running"}],
        }
    ]
    inspected = []
    monkeypatch.setattr(
        docker,
        "container_inspect",
        lambda name: inspected.append(name) or {"State": {"Running": True}},
    )
    assert runtime.pod_inspect("ollama")["State"]["Running"]
    assert inspected == ["custom-ai-server"]


def test_docker_removal_failure_is_reported(monkeypatch):
    monkeypatch.setattr(docker, "container_exists", lambda name: True)

    def fail(args, **kwargs):
        raise subprocess.CalledProcessError(1, args, output="busy")

    monkeypatch.setattr(docker, "_run", fail)
    with pytest.raises(docker.DockerError, match="busy"):
        docker.remove_pod("ollama")


@pytest.mark.parametrize(
    "detail", ["No such container: webui", "No such object: webui"]
)
@pytest.mark.parametrize(
    ("module", "runtime_cls"), [(docker, DockerRuntime), (podman, PodmanRuntime)]
)
def test_missing_container_is_distinct_from_runtime_failure(
    monkeypatch, detail, module, runtime_cls
):
    def inspect(*args, **kwargs):
        raise subprocess.CalledProcessError(
            1, [module.__name__, "inspect"], output="[]\n", stderr=detail
        )

    monkeypatch.setattr(module._cli, "run", inspect)
    assert runtime_cls().container_inspect("webui") is None


@pytest.mark.parametrize("output", ["[]", "null", "not JSON"])
def test_invalid_container_inspection_fails_closed(monkeypatch, output):
    monkeypatch.setattr(
        docker._cli, "run", lambda *args, **kwargs: SimpleNamespace(stdout=output)
    )
    with pytest.raises(ContainerRuntimeError, match="invalid inspection output"):
        DockerRuntime().container_inspect("webui")


@pytest.mark.parametrize(
    ("module", "runtime_cls"), [(docker, DockerRuntime), (podman, PodmanRuntime)]
)
def test_engine_failure_does_not_report_container_missing(
    monkeypatch, module, runtime_cls
):
    def inspect(*args, **kwargs):
        raise subprocess.CalledProcessError(
            1,
            [module.__name__, "inspect"],
            output="[]\n",
            stderr="Cannot connect to the container engine",
        )

    monkeypatch.setattr(module._cli, "run", inspect)
    with pytest.raises(ContainerRuntimeError, match="Cannot connect"):
        runtime_cls().container_exists("webui")
