from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Protocol

from airpods import podman


class ContainerRuntimeError(RuntimeError):
    """Raised when a container runtime operation fails."""


class ContainerRuntime(Protocol):
    """Abstract interface for container runtime operations."""

    def ensure_network(self, name: str) -> bool:
        """Create a network if it doesn't exist.

        Returns True if the network was created, False if it already existed.
        """
        ...

    def ensure_volume(self, name: str) -> bool:
        """Create a volume if it doesn't exist.

        Returns True if the volume was created, False if it already existed.
        """
        ...

    def pull_image(self, image: str) -> None:
        """Pull a container image."""
        ...

    def ensure_pod(
        self, pod: str, ports: Iterable[tuple[int, int]], network: str
    ) -> bool:
        """Create a pod if it doesn't exist.

        Returns True if the pod was created, False if it already existed.
        """
        ...

    def run_container(
        self,
        *,
        pod: str,
        name: str,
        image: str,
        env: Dict[str, str],
        volumes: Iterable[tuple[str, str]],
        gpu: bool = False,
        restart_policy: str = "unless-stopped",
        gpu_device_flag: Optional[str] = None,
    ) -> bool:
        """Run a container in a pod.

        Returns True if the container already existed and was replaced.
        """
        ...

    def container_exists(self, name: str) -> bool:
        """Check if a container exists."""
        ...

    def pod_exists(self, name: str) -> bool:
        """Check if a pod exists."""
        ...

    def stop_pod(self, name: str, timeout: int = 10) -> None:
        """Stop a pod."""
        ...

    def remove_pod(self, name: str) -> None:
        """Remove a pod."""
        ...

    def pod_status(self) -> List[Dict]:
        """Get status of all pods."""
        ...

    def pod_inspect(self, name: str) -> Optional[Dict]:
        """Inspect a pod and return its configuration."""
        ...

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
        ...


class PodmanRuntime:
    """Podman implementation of the container runtime interface."""

    def ensure_network(self, name: str) -> bool:
        try:
            return podman.ensure_network(name)
        except podman.PodmanError as exc:
            raise ContainerRuntimeError(str(exc)) from exc

    def ensure_volume(self, name: str) -> bool:
        try:
            return podman.ensure_volume(name)
        except podman.PodmanError as exc:
            raise ContainerRuntimeError(str(exc)) from exc

    def pull_image(self, image: str) -> None:
        try:
            podman.pull_image(image)
        except podman.PodmanError as exc:
            raise ContainerRuntimeError(str(exc)) from exc

    def ensure_pod(
        self, pod: str, ports: Iterable[tuple[int, int]], network: str
    ) -> bool:
        try:
            return podman.ensure_pod(pod, ports, network)
        except podman.PodmanError as exc:
            raise ContainerRuntimeError(str(exc)) from exc

    def run_container(
        self,
        *,
        pod: str,
        name: str,
        image: str,
        env: Dict[str, str],
        volumes: Iterable[tuple[str, str]],
        gpu: bool = False,
        restart_policy: str = "unless-stopped",
        gpu_device_flag: Optional[str] = None,
    ) -> bool:
        try:
            return podman.run_container(
                pod=pod,
                name=name,
                image=image,
                env=env,
                volumes=volumes,
                gpu=gpu,
                restart_policy=restart_policy,
                gpu_device_flag=gpu_device_flag,
            )
        except podman.PodmanError as exc:
            raise ContainerRuntimeError(str(exc)) from exc

    def container_exists(self, name: str) -> bool:
        return podman.container_exists(name)

    def pod_exists(self, name: str) -> bool:
        return podman.pod_exists(name)

    def stop_pod(self, name: str, timeout: int = 10) -> None:
        try:
            podman.stop_pod(name, timeout=timeout)
        except podman.PodmanError as exc:
            raise ContainerRuntimeError(str(exc)) from exc

    def remove_pod(self, name: str) -> None:
        try:
            podman.remove_pod(name)
        except podman.PodmanError as exc:
            raise ContainerRuntimeError(str(exc)) from exc

    def pod_status(self) -> List[Dict]:
        return podman.pod_status()

    def pod_inspect(self, name: str) -> Optional[Dict]:
        return podman.pod_inspect(name)

    def stream_logs(
        self,
        container: str,
        *,
        follow: bool = False,
        tail: Optional[int] = None,
        since: Optional[str] = None,
    ) -> int:
        return podman.stream_logs(container, follow=follow, tail=tail, since=since)


def get_runtime(prefer: str | None) -> ContainerRuntime:
    """Get a container runtime instance based on preference.

    Args:
        prefer: Runtime preference ("auto", "podman", "docker", or None).

    Returns:
        A ContainerRuntime implementation.

    Raises:
        ContainerRuntimeError: If the requested runtime is unsupported.
    """
    if prefer in (None, "auto", "podman"):
        return PodmanRuntime()

    if prefer == "docker":
        raise ContainerRuntimeError(
            "Docker is not supported yet. Please set runtime.prefer back to 'podman' or 'auto' and try again."
        )

    raise ContainerRuntimeError(f"Unknown runtime '{prefer}'")
