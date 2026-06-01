from __future__ import annotations

import shutil
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
        memory: Optional[str] = None,
        cpus: Optional[str] = None,
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


class _CLIRuntime:
    """Single Runtime class parameterized by the underlying CLI module.

    Replaces the previously duplicated PodmanRuntime and DockerRuntime classes.
    """

    def __init__(self, name: str, mod, error_cls: type) -> None:
        self._name = name
        self._mod = mod
        self._error = error_cls

    @property
    def runtime_name(self) -> str:
        return self._name

    def _wrap(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except self._error as exc:
            raise ContainerRuntimeError(str(exc)) from exc

    def ensure_volume(self, name: str) -> bool:
        return self._wrap(self._mod.ensure_volume, name)

    def pull_image(self, image: str) -> None:
        self._wrap(self._mod.pull_image, image)

    def ensure_pod(
        self,
        pod: str,
        ports: Iterable[tuple[int, int]],
        userns_mode: Optional[str] = None,
    ) -> bool:
        return self._wrap(self._mod.ensure_pod, pod, ports, userns_mode=userns_mode)

    def run_container(
        self,
        *,
        pod: str,
        name: str,
        image: str,
        env: Dict[str, str],
        volumes: Iterable[tuple[int, int]],
        gpu: bool = False,
        restart_policy: str = "unless-stopped",
        gpu_device_flag: Optional[str] = None,
        pids_limit: int = 2048,
        userns_mode: Optional[str] = None,
        entrypoint: Optional[str] = None,
        command: Optional[List[str]] = None,
        memory: Optional[str] = None,
        cpus: Optional[str] = None,
    ) -> bool:
        return self._wrap(
            self._mod.run_container,
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
            memory=memory,
            cpus=cpus,
        )

    def container_exists(self, name: str) -> bool:
        return self._mod.container_exists(name)

    def pod_exists(self, name: str) -> bool:
        return self._mod.pod_exists(name)

    def stop_pod(self, name: str, timeout: int = 10) -> None:
        self._wrap(self._mod.stop_pod, name, timeout=timeout)

    def remove_pod(self, name: str) -> None:
        self._wrap(self._mod.remove_pod, name)

    def pod_status(self) -> List[Dict]:
        return self._mod.pod_status()

    def pod_inspect(self, name: str) -> Optional[Dict]:
        return self._mod.pod_inspect(name)

    def stream_logs(
        self,
        container: str,
        *,
        follow: bool = False,
        tail: Optional[int] = None,
        since: Optional[str] = None,
    ) -> int:
        return self._mod.stream_logs(container, follow=follow, tail=tail, since=since)

    def image_size(self, image: str) -> Optional[str]:
        return self._mod.image_size(image)

    def image_exists(self, image: str) -> bool:
        return self._mod.image_exists(image)

    def image_size_bytes(self, image: str) -> Optional[int]:
        return self._mod.image_size_bytes(image)

    def get_remote_image_size(self, image: str) -> Optional[int]:
        return self._mod.get_remote_image_size(image)

    def list_volumes(self) -> List[str]:
        return self._mod.list_volumes()

    def remove_volume(self, name: str) -> None:
        self._wrap(self._mod.remove_volume, name)

    def remove_image(self, image: str) -> None:
        self._wrap(self._mod.remove_image, image)

    def exec_in_container(
        self, container: str, command: List[str], **kwargs
    ) -> subprocess.CompletedProcess:
        return self._wrap(self._mod.exec_in_container, container, command, **kwargs)

    def copy_to_container(self, src: str, container: str, dest: str) -> None:
        self._wrap(self._mod.copy_to_container, src, container, dest)

    def copy_from_container(self, container: str, src: str, dest: str) -> None:
        self._wrap(self._mod.copy_from_container, container, src, dest)

    def container_inspect(self, name: str) -> Optional[Dict]:
        return self._mod.container_inspect(name)

    def list_containers(self, filters: Optional[Dict] = None) -> List[Dict]:
        return self._mod.list_containers(filters)


class PodmanRuntime(_CLIRuntime):
    def __init__(self) -> None:
        super().__init__("podman", podman, podman.PodmanError)


class DockerRuntime(_CLIRuntime):
    def __init__(self) -> None:
        super().__init__("docker", docker, docker.DockerError)


def _runtime_available(runtime_name: str) -> bool:
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
        if _runtime_available("podman"):
            return PodmanRuntime()
        if _runtime_available("docker"):
            return DockerRuntime()
        raise ContainerRuntimeError(
            "No container runtime found. Please install either Podman or Docker."
        )

    raise ContainerRuntimeError(f"Unknown runtime '{prefer}'")
