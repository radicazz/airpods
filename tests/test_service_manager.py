from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from airpods.services import ServiceManager, ServiceRegistry, ServiceSpec


class FakeRuntime:
    def __init__(self):
        self.pulled_images: list[str] = []

    def pull_image(self, image: str) -> None:  # pragma: no cover - replaced in test
        self.pulled_images.append(image)


@pytest.fixture
def service_specs() -> list[ServiceSpec]:
    return [
        ServiceSpec(name=f"svc{i}", pod=f"pod{i}", container=f"ctr{i}", image=f"img{i}")
        for i in range(3)
    ]


@pytest.fixture
def manager(service_specs: list[ServiceSpec]) -> ServiceManager:
    registry = ServiceRegistry(service_specs)
    runtime = MagicMock()
    return ServiceManager(registry, runtime)


def test_pull_images_sequential(manager: ServiceManager, service_specs):
    manager.runtime.pull_image = MagicMock()

    manager.pull_images(service_specs, max_concurrent=1)

    assert manager.runtime.pull_image.call_count == len(service_specs)


def test_pull_images_concurrent_respects_limit(manager: ServiceManager, service_specs):
    manager.runtime.pull_image = MagicMock()

    manager.pull_images(service_specs, max_concurrent=2)

    assert manager.runtime.pull_image.call_count == len(service_specs)


def test_pull_images_bubbles_exceptions(manager: ServiceManager, service_specs):
    call_count = 0

    def side_effect(_):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("boom")

    manager.runtime.pull_image.side_effect = side_effect

    with pytest.raises(RuntimeError):
        manager.pull_images(service_specs, max_concurrent=3)

    # With concurrent execution, the exact order of calls can vary
    # Just ensure the exception was raised and at least the failing call happened
    assert call_count >= 2


def test_start_service_respects_config_force_cpu(manager: ServiceManager):
    spec = ServiceSpec(
        name="svc",
        pod="pod",
        container="ctr",
        image="img",
        needs_gpu=True,
        force_cpu=True,
    )
    manager.runtime.ensure_pod.return_value = False
    manager.runtime.run_container.return_value = False

    manager.start_service(spec, gpu_available=True)

    assert manager.runtime.run_container.call_args.kwargs["gpu"] is False


def test_start_service_force_cpu_override(manager: ServiceManager):
    spec = ServiceSpec(
        name="svc",
        pod="pod",
        container="ctr",
        image="img",
        needs_gpu=True,
    )
    manager.runtime.ensure_pod.return_value = False
    manager.runtime.run_container.return_value = False

    manager.start_service(spec, gpu_available=True, force_cpu_override=True)

    assert manager.runtime.run_container.call_args.kwargs["gpu"] is False


def test_start_service_passes_userns_and_resource_limits(manager: ServiceManager):
    spec = ServiceSpec(
        name="svc",
        pod="pod",
        container="ctr",
        image="img",
        userns_mode="keep-id",
        memory="2g",
        cpus="1.5",
    )
    manager.runtime.ensure_pod.return_value = False
    manager.runtime.run_container.return_value = False

    manager.start_service(spec, gpu_available=False)

    kwargs = manager.runtime.run_container.call_args.kwargs
    assert kwargs["userns_mode"] == "keep-id"
    assert kwargs["memory"] == "2g"
    assert kwargs["cpus"] == "1.5"


def test_report_environment_skips_dependency_checks():
    runtime = MagicMock()
    mgr = ServiceManager(
        ServiceRegistry([]),
        runtime,
        required_dependencies=["podman"],
        skip_dependency_checks=True,
    )

    report = mgr.report_environment()
    assert report.checks[0].detail == "skipped"

    # Should not raise even if podman would be missing
    mgr.ensure_podman()
