from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Literal,
    Optional,
    Sequence,
    Tuple,
)

from airpods import state
from airpods.runtime import ContainerRuntime, ContainerRuntimeError
from airpods.system import CheckResult, check_dependency, detect_gpu


class UnknownServiceError(ValueError):
    """Raised when the user references an unknown service name."""


@dataclass(frozen=True)
class VolumeMount:
    """Describe how a host path or Podman volume is attached."""

    source: str
    target: str

    @property
    def is_bind_mount(self) -> bool:
        return Path(self.source).is_absolute()

    def as_tuple(self) -> Tuple[str, str]:
        return self.source, self.target


@dataclass(frozen=True)
class ServiceSpec:
    """Specification for a containerized service."""

    name: str
    pod: str
    container: str
    image: str
    ports: List[Tuple[int, int]] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    env_factory: Optional[Callable[[], Dict[str, str]]] = None
    volumes: List[VolumeMount] = field(default_factory=list)
    network_aliases: List[str] = field(default_factory=list)
    needs_gpu: bool = False
    health_path: Optional[str] = None
    force_cpu: bool = False

    def runtime_env(self) -> Dict[str, str]:
        """Merge static env with runtime env from factory."""
        data = dict(self.env)
        if self.env_factory:
            data.update(self.env_factory())
        return data


@dataclass(frozen=True)
class VolumeEnsureResult:
    source: str
    target: str
    kind: Literal["bind", "volume"]
    created: bool


@dataclass(frozen=True)
class ServiceStartResult:
    spec: ServiceSpec
    pod_created: bool
    container_replaced: bool


ProgressPhase = Literal["start", "end"]
ProgressCallback = Callable[[ProgressPhase, int, int, ServiceSpec], None]


class ServiceRegistry:
    """Simple catalog + resolver for configured services."""

    def __init__(self, specs: Sequence[ServiceSpec]):
        self._order = list(specs)
        self._specs = {spec.name: spec for spec in specs}

    def __iter__(self) -> Iterator[ServiceSpec]:
        return iter(self._order)

    def all(self) -> List[ServiceSpec]:
        return list(self._order)

    def get(self, name: str) -> Optional[ServiceSpec]:
        return self._specs.get(name)

    def names(self) -> List[str]:
        return [spec.name for spec in self._order]

    def resolve(self, names: Optional[Sequence[str]]) -> List[ServiceSpec]:
        if not names:
            return self.all()
        missing = [name for name in names if name not in self._specs]
        if missing:
            raise UnknownServiceError(
                f"unknown service(s): {', '.join(missing)}. available: {', '.join(self.names())}"
            )
        return [self._specs[name] for name in names]


@dataclass(frozen=True)
class EnvironmentReport:
    checks: List[CheckResult]
    gpu_available: bool
    gpu_detail: str

    @property
    def missing(self) -> List[str]:
        return [check.name for check in self.checks if not check.ok]


class ServiceManager:
    """Performs the common Podman orchestration tasks."""

    def __init__(
        self,
        registry: ServiceRegistry,
        runtime: ContainerRuntime,
        *,
        network_name: str = "airpods_network",
        network_driver: str = "bridge",
        network_subnet: str | None = None,
        network_gateway: str | None = None,
        network_dns_servers: list[str] | None = None,
        network_ipv6: bool = False,
        network_internal: bool = False,
        restart_policy: str = "unless-stopped",
        gpu_device_flag: str | None = None,
        required_dependencies: Optional[Sequence[str]] = None,
        optional_dependencies: Optional[Sequence[str]] = None,
        skip_dependency_checks: bool = False,
    ):
        self.registry = registry
        self.runtime = runtime
        self.network_name = network_name
        self.network_driver = network_driver
        self.network_subnet = network_subnet
        self.network_gateway = network_gateway
        self.network_dns_servers = network_dns_servers or []
        self.network_ipv6 = network_ipv6
        self.network_internal = network_internal
        self.restart_policy = restart_policy
        self.gpu_device_flag = gpu_device_flag
        self.required_dependencies = list(
            required_dependencies or ["podman", "podman-compose", "uv"]
        )
        self.optional_dependencies = list(optional_dependencies or [])
        self.skip_dependency_checks = skip_dependency_checks

    # ----------------------------------------------------------------------------------
    # Discovery + validation helpers
    # ----------------------------------------------------------------------------------
    def resolve(self, names: Optional[Sequence[str]]) -> List[ServiceSpec]:
        """Resolve service names to specs, or return all if none specified."""
        return self.registry.resolve(names)

    def report_environment(self) -> EnvironmentReport:
        """Check system dependencies and GPU availability."""
        if self.skip_dependency_checks:
            checks = [
                CheckResult(name=dep, ok=True, detail="skipped")
                for dep in self.required_dependencies
            ]
        else:
            checks = [
                check_dependency(dep, ["--version"])
                for dep in self.required_dependencies
            ]
        gpu_available, gpu_detail = detect_gpu()
        return EnvironmentReport(
            checks=checks, gpu_available=gpu_available, gpu_detail=gpu_detail
        )

    def ensure_podman(self) -> None:
        """Verify podman is installed and available."""
        if self.skip_dependency_checks:
            return
        report = self.report_environment()
        if "podman" in report.missing:
            raise ContainerRuntimeError("podman is required; install it and retry.")

    # ----------------------------------------------------------------------------------
    # Pod + container orchestration
    # ----------------------------------------------------------------------------------
    def ensure_network(self) -> bool:
        """Create the shared pod network if it doesn't exist."""
        return self.runtime.ensure_network(
            self.network_name,
            driver=self.network_driver,
            subnet=self.network_subnet,
            gateway=self.network_gateway,
            dns_servers=self.network_dns_servers,
            ipv6=self.network_ipv6,
            internal=self.network_internal,
        )

    def ensure_volumes(self, specs: Iterable[ServiceSpec]) -> List[VolumeEnsureResult]:
        """Create all volumes required by the given service specs."""
        results: List[VolumeEnsureResult] = []
        handled: set[tuple[str, str]] = set()
        for spec in specs:
            for mount in spec.volumes:
                key = ("bind" if mount.is_bind_mount else "volume", mount.source)
                if key in handled:
                    continue
                handled.add(key)
                if mount.is_bind_mount:
                    _, created = state.ensure_volume_source(mount.source)
                    results.append(
                        VolumeEnsureResult(
                            source=mount.source,
                            target=mount.target,
                            kind="bind",
                            created=created,
                        )
                    )
                    continue
                created = self.runtime.ensure_volume(mount.source)
                results.append(
                    VolumeEnsureResult(
                        source=mount.source,
                        target=mount.target,
                        kind="volume",
                        created=created,
                    )
                )
        return results

    def pull_images(
        self,
        specs: Iterable[ServiceSpec],
        *,
        progress_callback: ProgressCallback | None = None,
        max_concurrent: int = 1,
    ) -> None:
        """Pull container images for the given service specs."""
        spec_list = list(specs)
        total = len(spec_list)
        if total == 0:
            return

        max_workers = max(1, max_concurrent)

        def _pull_single(index: int, spec: ServiceSpec) -> ServiceSpec:
            if progress_callback:
                progress_callback("start", index, total, spec)
            self.runtime.pull_image(spec.image)
            if progress_callback:
                progress_callback("end", index, total, spec)
            return spec

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_pull_single, index, spec): (index, spec)
                for index, spec in enumerate(spec_list, start=1)
            }
            for future in as_completed(futures):
                exc = future.exception()
                if exc:
                    # Cancel remaining futures and re-raise the exception
                    for f in futures:
                        f.cancel()
                    raise exc

    def get_image_sizes(self, specs: Iterable[ServiceSpec]) -> Dict[str, Optional[str]]:
        """Get image sizes for all specs."""
        sizes = {}
        for spec in specs:
            sizes[spec.name] = self.runtime.image_size(spec.image)
        return sizes

    def start_service(
        self,
        spec: ServiceSpec,
        *,
        gpu_available: bool,
        force_cpu_override: bool = False,
    ) -> ServiceStartResult:
        """Start a service by creating its pod and running its container."""
        pod_created = self.runtime.ensure_pod(
            spec.pod, spec.ports, network=self.network_name
        )
        gpu_enabled = spec.needs_gpu and not spec.force_cpu and not force_cpu_override
        container_replaced = self.runtime.run_container(
            pod=spec.pod,
            name=spec.container,
            image=spec.image,
            env=spec.runtime_env(),
            volumes=[mount.as_tuple() for mount in spec.volumes],
            network_aliases=spec.network_aliases,
            gpu=gpu_enabled and gpu_available,
            restart_policy=self.restart_policy,
            gpu_device_flag=self.gpu_device_flag,
        )
        return ServiceStartResult(
            spec=spec, pod_created=pod_created, container_replaced=container_replaced
        )

    def container_exists(self, spec: ServiceSpec) -> bool:
        """Return True if the service's container already exists."""
        return self.runtime.container_exists(spec.container)

    def stop_service(
        self, spec: ServiceSpec, *, remove: bool = False, timeout: int = 10
    ) -> bool:
        """Stop a service's pod; returns True if pod existed."""
        if not self.runtime.pod_exists(spec.pod):
            return False
        self.runtime.stop_pod(spec.pod, timeout=timeout)
        if remove:
            self.runtime.remove_pod(spec.pod)
        return True

    def service_ports(self, spec: ServiceSpec) -> Dict[str, List[Dict[str, str]]]:
        """Extract port bindings from a service's pod."""
        inspect_info = self.runtime.pod_inspect(spec.pod) or {}
        infra = inspect_info.get("InfraConfig", {})
        return infra.get("PortBindings", {})

    def pod_status_rows(self) -> Dict[str, Dict[str, Any]]:
        """Return pod status indexed by pod name."""
        return {row.get("Name"): row for row in self.runtime.pod_status()}

    def stream_logs(
        self,
        container: str,
        *,
        follow: bool = False,
        tail: Optional[int] = None,
        since: Optional[str] = None,
    ) -> int:
        """Stream logs from a container.

        Returns the exit code of the log streaming process.
        """
        return self.runtime.stream_logs(
            container, follow=follow, tail=tail, since=since
        )
