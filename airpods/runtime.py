from __future__ import annotations

import subprocess
from typing import Dict, Iterable, List, Optional, Protocol

from airpods import docker, podman


class ContainerRuntimeError(RuntimeError):
    """Raised when a container runtime operation fails."""


class ContainerRuntime(Protocol):
    """Abstract interface for container runtime operations."""

    @property
    def runtime_name(self) -> str:
        """Return the runtime name ('podman' or 'docker')."""
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
        self,
        pod: str,
        ports: Iterable[tuple[int, int]],
        userns_mode: Optional[str] = None,
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
        pids_limit: int = 2048,
        userns_mode: Optional[str] = None,
        entrypoint: Optional[str] = None,
        command: Optional[List[str]] = None,
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

    def image_size(self, image: str) -> Optional[str]:
        """Get the size of an image in human-readable format."""
        ...

    def image_exists(self, image: str) -> bool:
        """Check if an image exists locally."""
        ...

    def image_size_bytes(self, image: str) -> Optional[int]:
        """Get the size of an image in bytes."""
        ...

    def get_remote_image_size(self, image: str) -> Optional[int]:
        """Get the size of a remote image in bytes."""
        ...

    def list_volumes(self) -> List[str]:
        """List all volumes matching airpods pattern."""
        ...

    def remove_volume(self, name: str) -> None:
        """Remove a volume."""
        ...

    def remove_image(self, image: str) -> None:
        """Remove an image."""
        ...

    def exec_in_container(
        self, container: str, command: List[str], **kwargs
    ) -> subprocess.CompletedProcess:
        """Execute a command inside a running container."""
        ...

    def copy_to_container(self, src: str, container: str, dest: str) -> None:
        """Copy a file from host to container."""
        ...

    def copy_from_container(self, container: str, src: str, dest: str) -> None:
        """Copy a file from container to host."""
        ...

    def container_inspect(self, name: str) -> Optional[Dict]:
        """Inspect a container and return its configuration."""
        ...

    def list_containers(self, filters: Optional[Dict] = None) -> List[Dict]:
        """List containers matching filters."""
        ...


class PodmanRuntime:
    """Podman implementation of the container runtime interface."""

    @property
    def runtime_name(self) -> str:
        """Return the runtime name ('podman')."""
        return "podman"

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
        self,
        pod: str,
        ports: Iterable[tuple[int, int]],
        userns_mode: Optional[str] = None,
    ) -> bool:
        try:
            return podman.ensure_pod(pod, ports, userns_mode=userns_mode)
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
        pids_limit: int = 2048,
        userns_mode: Optional[str] = None,
        entrypoint: Optional[str] = None,
        command: Optional[List[str]] = None,
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
                pids_limit=pids_limit,
                userns_mode=userns_mode,
                entrypoint=entrypoint,
                command=command,
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

    def image_size(self, image: str) -> Optional[str]:
        return podman.image_size(image)

    def image_exists(self, image: str) -> bool:
        return podman.image_exists(image)

    def image_size_bytes(self, image: str) -> Optional[int]:
        return podman.image_size_bytes(image)

    def get_remote_image_size(self, image: str) -> Optional[int]:
        return podman.get_remote_image_size(image)

    def list_volumes(self) -> List[str]:
        return podman.list_volumes()

    def remove_volume(self, name: str) -> None:
        try:
            podman.remove_volume(name)
        except podman.PodmanError as exc:
            raise ContainerRuntimeError(str(exc)) from exc

    def remove_image(self, image: str) -> None:
        try:
            podman.remove_image(image)
        except podman.PodmanError as exc:
            raise ContainerRuntimeError(str(exc)) from exc

    def exec_in_container(
        self, container: str, command: List[str], **kwargs
    ) -> subprocess.CompletedProcess:
        try:
            return podman.exec_in_container(container, command, **kwargs)
        except podman.PodmanError as exc:
            raise ContainerRuntimeError(str(exc)) from exc

    def copy_to_container(self, src: str, container: str, dest: str) -> None:
        try:
            podman.copy_to_container(src, container, dest)
        except podman.PodmanError as exc:
            raise ContainerRuntimeError(str(exc)) from exc

    def copy_from_container(self, container: str, src: str, dest: str) -> None:
        try:
            podman.copy_from_container(container, src, dest)
        except podman.PodmanError as exc:
            raise ContainerRuntimeError(str(exc)) from exc

    def container_inspect(self, name: str) -> Optional[Dict]:
        return podman.container_inspect(name)

    def list_containers(self, filters: Optional[Dict] = None) -> List[Dict]:
        return podman.list_containers(filters)


class DockerRuntime:
    """Docker implementation of the container runtime interface."""

    @property
    def runtime_name(self) -> str:
        """Return the runtime name ('docker')."""
        return "docker"

    def ensure_volume(self, name: str) -> bool:
        try:
            return docker.ensure_volume(name)
        except docker.DockerError as exc:
            raise ContainerRuntimeError(str(exc)) from exc

    def pull_image(self, image: str) -> None:
        try:
            docker.pull_image(image)
        except docker.DockerError as exc:
            raise ContainerRuntimeError(str(exc)) from exc

    def ensure_pod(
        self,
        pod: str,
        ports: Iterable[tuple[int, int]],
        userns_mode: Optional[str] = None,
    ) -> bool:
        try:
            return docker.ensure_pod(pod, ports, userns_mode=userns_mode)
        except docker.DockerError as exc:
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
        pids_limit: int = 2048,
        userns_mode: Optional[str] = None,
        entrypoint: Optional[str] = None,
        command: Optional[List[str]] = None,
    ) -> bool:
        try:
            return docker.run_container(
                pod=pod,
                name=name,
                image=image,
                env=env,
                volumes=volumes,
                gpu=gpu,
                restart_policy=restart_policy,
                gpu_device_flag=gpu_device_flag,
                pids_limit=pids_limit,
                userns_mode=userns_mode,
                entrypoint=entrypoint,
                command=command,
            )
        except docker.DockerError as exc:
            raise ContainerRuntimeError(str(exc)) from exc

    def container_exists(self, name: str) -> bool:
        return docker.container_exists(name)

    def pod_exists(self, name: str) -> bool:
        return docker.pod_exists(name)

    def stop_pod(self, name: str, timeout: int = 10) -> None:
        try:
            docker.stop_pod(name, timeout=timeout)
        except docker.DockerError as exc:
            raise ContainerRuntimeError(str(exc)) from exc

    def remove_pod(self, name: str) -> None:
        try:
            docker.remove_pod(name)
        except docker.DockerError as exc:
            raise ContainerRuntimeError(str(exc)) from exc

    def pod_status(self) -> List[Dict]:
        return docker.pod_status()

    def pod_inspect(self, name: str) -> Optional[Dict]:
        return docker.pod_inspect(name)

    def stream_logs(
        self,
        container: str,
        *,
        follow: bool = False,
        tail: Optional[int] = None,
        since: Optional[str] = None,
    ) -> int:
        return docker.stream_logs(container, follow=follow, tail=tail, since=since)

    def image_size(self, image: str) -> Optional[str]:
        return docker.image_size(image)

    def image_exists(self, image: str) -> bool:
        return docker.image_exists(image)

    def image_size_bytes(self, image: str) -> Optional[int]:
        return docker.image_size_bytes(image)

    def get_remote_image_size(self, image: str) -> Optional[int]:
        return docker.get_remote_image_size(image)

    def list_volumes(self) -> List[str]:
        return docker.list_volumes()

    def remove_volume(self, name: str) -> None:
        try:
            docker.remove_volume(name)
        except docker.DockerError as exc:
            raise ContainerRuntimeError(str(exc)) from exc

    def remove_image(self, image: str) -> None:
        try:
            docker.remove_image(image)
        except docker.DockerError as exc:
            raise ContainerRuntimeError(str(exc)) from exc

    def exec_in_container(
        self, container: str, command: List[str], **kwargs
    ) -> subprocess.CompletedProcess:
        try:
            return docker.exec_in_container(container, command, **kwargs)
        except docker.DockerError as exc:
            raise ContainerRuntimeError(str(exc)) from exc

    def copy_to_container(self, src: str, container: str, dest: str) -> None:
        try:
            docker.copy_to_container(src, container, dest)
        except docker.DockerError as exc:
            raise ContainerRuntimeError(str(exc)) from exc

    def copy_from_container(self, container: str, src: str, dest: str) -> None:
        try:
            docker.copy_from_container(container, src, dest)
        except docker.DockerError as exc:
            raise ContainerRuntimeError(str(exc)) from exc

    def container_inspect(self, name: str) -> Optional[Dict]:
        return docker.container_inspect(name)

    def list_containers(self, filters: Optional[Dict] = None) -> List[Dict]:
        return docker.list_containers(filters)


def _runtime_available(runtime_name: str) -> bool:
    """Check if a container runtime is available on the system.

    Args:
        runtime_name: Name of the runtime ("podman" or "docker")

    Returns:
        True if the runtime binary is available in PATH
    """
    import shutil

    return shutil.which(runtime_name) is not None


def get_runtime(prefer: str | None) -> ContainerRuntime:
    """Get a container runtime instance based on preference.

    Args:
        prefer: Runtime preference ("auto", "podman", "docker", or None).

    Returns:
        A ContainerRuntime implementation.

    Raises:
        ContainerRuntimeError: If the requested runtime is unsupported or unavailable.
    """
    if prefer == "podman":
        if not _runtime_available("podman"):
            raise ContainerRuntimeError(
                "Runtime preference is set to 'podman' but Podman is not installed."
            )
        return PodmanRuntime()

    if prefer == "docker":
        if not _runtime_available("docker"):
            raise ContainerRuntimeError(
                "Runtime preference is set to 'docker' but Docker is not installed."
            )
        return DockerRuntime()

    if prefer in (None, "auto"):
        # Auto-detect: prefer podman, fall back to docker, error if neither
        if _runtime_available("podman"):
            return PodmanRuntime()
        if _runtime_available("docker"):
            return DockerRuntime()
        raise ContainerRuntimeError(
            "No container runtime found. Please install either Podman or Docker."
        )

    raise ContainerRuntimeError(f"Unknown runtime '{prefer}'")
