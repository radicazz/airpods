from __future__ import annotations

import subprocess

import pytest

from airpods import system


def _completed(stdout: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout)


def test_run_command_success(monkeypatch):
    monkeypatch.setattr(system.subprocess, "run", lambda *a, **k: _completed(" ok \n"))
    assert system._run_command(["x"]) == (True, "ok")


def test_run_command_missing_binary(monkeypatch):
    def _raise(*_a, **_k):
        raise FileNotFoundError("nope")

    monkeypatch.setattr(system.subprocess, "run", _raise)
    ok, detail = system._run_command(["x"])
    assert not ok and "nope" in detail


def test_run_command_failure_includes_output(monkeypatch):
    def _raise(*_a, **_k):
        raise subprocess.CalledProcessError(1, ["x"], output="driver mismatch")

    monkeypatch.setattr(system.subprocess, "run", _raise)
    assert system._run_command(["x"]) == (False, "driver mismatch")


def test_check_dependency_states(monkeypatch):
    monkeypatch.setattr(system.shutil, "which", lambda _n: None)
    result = system.check_dependency("podman")
    assert not result.ok and "not found" in result.detail

    monkeypatch.setattr(system.shutil, "which", lambda _n: "/usr/bin/podman")
    assert system.check_dependency("podman").detail == "available"

    monkeypatch.setattr(system, "_run_command", lambda _a: (True, "podman 5.0"))
    assert system.check_dependency("podman", ["--version"]).detail == "podman 5.0"

    monkeypatch.setattr(system, "_run_command", lambda _a: (False, "boom"))
    failed = system.check_dependency("podman", ["--version"])
    assert not failed.ok and failed.detail == "unable to run"


@pytest.mark.parametrize(
    "which,run,expected",
    [
        (None, (True, ""), (False, "nvidia-smi not found")),
        ("/x", (False, "err"), (False, "nvidia-smi failed")),
        ("/x", (True, "\n"), (False, "no GPUs detected")),
        ("/x", (True, "A\nB\n"), (True, "A, B")),
    ],
)
def test_detect_gpu(monkeypatch, which, run, expected):
    monkeypatch.setattr(system.shutil, "which", lambda _n: which)
    monkeypatch.setattr(system, "_run_command", lambda _a: run)
    assert system.detect_gpu() == expected


def test_detect_cuda_compute_capability(monkeypatch):
    monkeypatch.setattr(system.shutil, "which", lambda _n: None)
    assert system.detect_cuda_compute_capability() == (
        False,
        "nvidia-smi not found",
        None,
    )

    monkeypatch.setattr(system.shutil, "which", lambda _n: "/x")
    monkeypatch.setattr(system, "_run_command", lambda _a: (False, ""))
    assert system.detect_cuda_compute_capability()[0] is False

    monkeypatch.setattr(system, "_run_command", lambda _a: (True, ""))
    assert system.detect_cuda_compute_capability()[1] == "no GPUs detected"

    monkeypatch.setattr(
        system, "_run_command", lambda _a: (True, "NVIDIA GTX 1650, 7.5")
    )
    assert system.detect_cuda_compute_capability() == (True, "NVIDIA GTX 1650", (7, 5))

    monkeypatch.setattr(system, "_run_command", lambda _a: (True, "garbage"))
    assert system.detect_cuda_compute_capability()[0] is False
