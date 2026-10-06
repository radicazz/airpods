"""Regression coverage for runtime reliability."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from airpods import docker
from airpods.runtime import ContainerRuntimeError, DockerRuntime


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
def test_missing_container_is_distinct_from_runtime_failure(monkeypatch, detail):
    def inspect(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["docker", "inspect"], stderr=detail)

    monkeypatch.setattr(docker._cli, "run", inspect)
    assert DockerRuntime().container_inspect("webui") is None


@pytest.mark.parametrize("output", ["[]", "null", "not JSON"])
def test_invalid_container_inspection_fails_closed(monkeypatch, output):
    monkeypatch.setattr(
        docker._cli, "run", lambda *args, **kwargs: SimpleNamespace(stdout=output)
    )
    with pytest.raises(ContainerRuntimeError, match="invalid inspection output"):
        DockerRuntime().container_inspect("webui")


def test_engine_failure_does_not_report_container_missing(monkeypatch):
    def inspect(*args, **kwargs):
        raise subprocess.CalledProcessError(
            1, ["docker", "inspect"], stderr="Cannot connect to the Docker daemon"
        )

    monkeypatch.setattr(docker._cli, "run", inspect)
    with pytest.raises(ContainerRuntimeError, match="Cannot connect"):
        DockerRuntime().container_exists("webui")
