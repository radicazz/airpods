"""Unit tests for podman runtime helpers."""

from __future__ import annotations

from typing import List

from airpods import podman as podman_module


class _Proc:
    def __init__(self, stdout: str):
        self.stdout = stdout


def test_run_container_passes_userns_and_resource_limits(monkeypatch):
    calls: List[List[str]] = []

    def fake_run(args, capture=True, check=True):  # noqa: ARG001 - signature match
        calls.append(args)
        return _Proc("")

    monkeypatch.setattr(podman_module, "_run", fake_run)
    monkeypatch.setattr(podman_module, "container_exists", lambda _: False)

    podman_module.run_container(
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
