"""Unit tests for docker runtime helpers.

These tests are intentionally mock-based so they can run on systems without
Docker installed.
"""

from __future__ import annotations

from typing import List

from airpods import docker as docker_module


class _Proc:
    def __init__(self, stdout: str):
        self.stdout = stdout


def test_list_containers_parses_json_lines(monkeypatch):
    calls: List[List[str]] = []

    def fake_run(args, capture=True, check=True):  # noqa: ARG001 - signature match
        calls.append(args)
        return _Proc(
            "\n".join(
                [
                    '{"Names":"ollama-0","Status":"Up 5 seconds"}',
                    '{"Names":"open-webui-0","Status":"Exited (0) 2 minutes ago"}',
                    "",
                ]
            )
        )

    monkeypatch.setattr(docker_module, "_run", fake_run)

    containers = docker_module.list_containers()
    assert len(containers) == 2
    assert containers[0]["Names"] == "ollama-0"
    assert containers[1]["Names"] == "open-webui-0"
    assert calls[0][:4] == ["ps", "--all", "--format", "{{json .}}"]


def test_list_containers_passes_filters(monkeypatch):
    calls: List[List[str]] = []

    def fake_run(args, capture=True, check=True):  # noqa: ARG001 - signature match
        calls.append(args)
        return _Proc("")

    monkeypatch.setattr(docker_module, "_run", fake_run)

    docker_module.list_containers({"name": "ollama"})
    assert "--filter" in calls[0]
    assert "name=ollama" in calls[0]


def test_pod_status_groups_by_prefix_and_normalizes_status(monkeypatch):
    def fake_run(args, capture=True, check=True):  # noqa: ARG001 - signature match
        return _Proc(
            "\n".join(
                [
                    '{"Names":"ollama-0","Status":"Up 5 seconds"}',
                    '{"Names":"open-webui-0","Status":"Exited (0) 2 minutes ago"}',
                    '{"Names":"comfyui-0","Status":"Created"}',
                ]
            )
        )

    monkeypatch.setattr(docker_module, "_run", fake_run)

    pods = {row["Name"]: row for row in docker_module.pod_status()}
    assert pods["ollama"]["Status"] == "Running"
    assert pods["open-webui"]["Status"] == "Exited"
    assert pods["comfyui"]["Status"] == "Created"


def test_run_container_passes_userns_and_resource_limits(monkeypatch):
    calls: List[List[str]] = []

    def fake_run(args, capture=True, check=True):  # noqa: ARG001 - signature match
        calls.append(args)
        return _Proc("")

    monkeypatch.setattr(docker_module, "_run", fake_run)
    monkeypatch.setattr(docker_module, "container_exists", lambda _: False)

    docker_module.run_container(
        pod="ollama",
        name="ollama-0",
        image="docker.io/ollama/ollama:latest",
        env={},
        volumes=[],
        userns_mode="keep-id",
        memory="2g",
        cpus="1.5",
    )

    run_args = calls[-1]
    assert "--userns" in run_args and "keep-id" in run_args
    assert "--memory" in run_args and "2g" in run_args
    assert "--cpus" in run_args and "1.5" in run_args
