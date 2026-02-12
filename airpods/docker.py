from __future__ import annotations

import json
import shlex
import subprocess
from typing import Dict, Iterable, List, Optional

from .logging import console


class DockerError(RuntimeError):
    pass


def _run(
    args: List[str],
    capture: bool = True,
    check: bool = True,
    timeout: Optional[float] = None,
) -> subprocess.CompletedProcess[str]:
    """Run a docker command and return the completed process.

    Output is always captured so Rich spinners stay clean. Callers can read
    proc.stdout when needed.
    """
    cmd = ["docker"] + args
    proc = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check,
        timeout=timeout,
    )
    return proc


def _format_exc_output(exc: subprocess.CalledProcessError) -> str:
    output = getattr(exc, "stdout", None) or getattr(exc, "output", None)
    return output.strip() if output else ""


def _ps_json(filters: Optional[Dict] = None) -> List[Dict]:
    """Return docker ps results as a list of dicts.

    Docker doesn't support Podman's `--format json` output. Instead we use a Go
    template that emits one JSON object per line.
    """
    args: List[str] = ["ps", "--all", "--format", "{{json .}}"]
    if filters:
        for key, value in filters.items():
            args.extend(["--filter", f"{key}={value}"])

    try:
        proc = _run(args)
    except subprocess.CalledProcessError:
        return []

    containers: List[Dict] = []
    for line in (proc.stdout or "").splitlines():
        if not line.strip():
            continue
        try:
            containers.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return containers


def _normalize_container_status(status: str) -> str:
    """Map docker ps 'Status' strings to Podman-like status values."""
    value = (status or "").strip()
    if not value:
        return "Unknown"
    if value == "running":
        return "Running"

    # `docker ps` typically prefixes with "Up", "Exited", etc.
    if value.startswith("Up"):
        return "Running"
    if value.startswith("Exited"):
        return "Exited"
    if value.startswith("Created"):
        return "Created"
    if value.startswith("Restarting"):
        return "Restarting"
    if value.startswith("Paused"):
        return "Paused"

    return "Unknown"


def _merge_pod_status(current: str, incoming: str) -> str:
    """Choose an overall pod status from container statuses."""
    order = {
        "Running": 0,
        "Restarting": 1,
        "Paused": 2,
        "Exited": 3,
        "Created": 4,
        "Unknown": 5,
    }
    return incoming if order.get(incoming, 99) < order.get(current, 99) else current


def volume_exists(name: str) -> bool:
    try:
        _run(["volume", "inspect", name])
        return True
    except subprocess.CalledProcessError:
        return False


def ensure_volume(name: str) -> bool:
    if volume_exists(name):
        return False
    try:
        _run(["volume", "create", name], capture=False)
    except subprocess.CalledProcessError as exc:
        detail = _format_exc_output(exc)
        msg = f"failed to create volume {name}"
        if detail:
            msg = f"{msg}: {detail}"
        raise DockerError(msg) from exc
    return True


def list_volumes() -> List[str]:
    """List all Docker volumes."""
    try:
        proc = _run(["volume", "ls", "--format", "{{.Name}}"])
        return [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    except subprocess.CalledProcessError:
        return []


def remove_volume(name: str) -> None:
    """Remove a Docker volume by name."""
    try:
        _run(["volume", "rm", "--force", name], capture=False)
    except subprocess.CalledProcessError as exc:
        detail = _format_exc_output(exc)
        msg = f"failed to remove volume {name}"
        if detail:
            msg = f"{msg}: {detail}"
        raise DockerError(msg) from exc


def pull_image(image: str) -> None:
    try:
        _run(["pull", image], capture=False)
    except subprocess.CalledProcessError as exc:
        detail = _format_exc_output(exc)
        msg = f"failed to pull image {image}"
        if detail:
            msg = f"{msg}: {detail}"
        raise DockerError(msg) from exc


def image_exists(image: str) -> bool:
    """Check if an image exists locally."""
    try:
        _run(["image", "inspect", image])
        return True
    except subprocess.CalledProcessError:
        return False


def image_size(image: str) -> Optional[str]:
    """Get the size of an image in human-readable format."""
    try:
        proc = _run(["image", "inspect", image, "--format", "{{.Size}}"])
        size_bytes = int(proc.stdout.strip())
        # Convert to human-readable format
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f}{unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f}TB"
    except (subprocess.CalledProcessError, ValueError):
        return None


def image_size_bytes(image: str) -> Optional[int]:
    """Get the size of an image in bytes."""
    try:
        proc = _run(["image", "inspect", image, "--format", "{{.Size}}"])
        return int(proc.stdout.strip())
    except (subprocess.CalledProcessError, ValueError):
        return None


def get_remote_image_size(image: str) -> Optional[int]:
    """Get the size of a remote image in bytes without pulling it.

    This function attempts to query the remote registry for image size.
    Returns None if the size cannot be determined.
    """
    # First check if the image exists locally - if so, use local size
    if image_exists(image):
        return image_size_bytes(image)

    # Try using skopeo to inspect remote image (if available)
    try:
        proc = subprocess.run(
            ["skopeo", "inspect", f"docker://{image}"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode == 0:
            data = json.loads(proc.stdout)
            # skopeo reports Size in the manifest
            if "Size" in data:
                return int(data["Size"])
    except (OSError, FileNotFoundError, json.JSONDecodeError, ValueError, KeyError):
        # skopeo not available or failed to parse - that's OK
        pass

    # If we can't determine the size, return None
    # The calling code will handle this gracefully
    return None


def pod_exists(pod: str) -> bool:
    """Check if a 'pod' exists (Docker uses containers, not pods).

    For Docker, we check if the primary container with the pod name exists.
    """
    return container_exists(f"{pod}-0")


def container_exists(name: str) -> bool:
    try:
        _run(["container", "inspect", name])
        return True
    except subprocess.CalledProcessError:
        return False


def ensure_pod(
    pod: str,
    ports: Iterable[tuple[int, int]],
    userns_mode: Optional[str] = None,
) -> bool:
    """Create a 'pod' (no-op for Docker with host networking).

    Docker doesn't have pods. Since we use --network host, containers bind
    directly to host ports. The pod concept is just a naming convention.
    """
    # No-op for Docker - pods are just a logical grouping via naming
    return False


def run_container(
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
    existed = container_exists(name)

    # If container exists and is running, don't replace it
    if existed:
        try:
            proc = _run(["container", "inspect", name, "--format", "{{.State.Status}}"])
            status = proc.stdout.strip()
            if status == "running":
                return True  # Container already running, no need to replace
        except subprocess.CalledProcessError:
            pass  # Fall through to replace

    # Stop and remove existing container if it exists
    if existed:
        try:
            _run(["container", "stop", name], check=False)
            _run(["container", "rm", name], check=False)
        except subprocess.CalledProcessError:
            pass

    args: List[str] = [
        "run",
        "--detach",
        "--name",
        name,
        "--restart",
        restart_policy,
        "--pids-limit",
        str(pids_limit),
        "--network",
        "host",  # Use host networking instead of --pod
    ]

    if userns_mode:
        args.extend(["--userns", userns_mode])
    if memory:
        args.extend(["--memory", memory])
    if cpus:
        args.extend(["--cpus", cpus])

    if entrypoint:
        args.extend(["--entrypoint", entrypoint])

    for key, val in env.items():
        args.extend(["-e", f"{key}={val}"])
    for volume_name, dest in volumes:
        args.extend(["-v", f"{volume_name}:{dest}"])
    if gpu and gpu_device_flag:
        args.extend(shlex.split(gpu_device_flag))
    args.append(image)
    if command:
        args.extend(command)
    try:
        _run(args, capture=False)
    except subprocess.CalledProcessError as exc:
        detail = _format_exc_output(exc)
        msg = f"failed to start container {name}"
        if detail:
            msg = f"{msg}: {detail}"
        raise DockerError(msg) from exc
    return existed


def pod_status() -> List[Dict]:
    """Get status of all 'pods' (containers in Docker).

    Returns container data in a format compatible with Podman's pod status.
    """
    containers = _ps_json()

    # Group containers by pod name (extracted from container name pattern)
    pods: Dict[str, Dict] = {}
    for container in containers:
        name = container.get("Names", "")
        if not name:
            continue

        raw_status = container.get("State") or container.get("Status") or ""
        status = _normalize_container_status(str(raw_status))

        # Extract pod name from container naming pattern (e.g., "ollama-0" -> "ollama")
        pod_name = name.rsplit("-", 1)[0] if "-" in name else name

        if pod_name not in pods:
            pods[pod_name] = {"Name": pod_name, "Status": status, "Containers": []}
        else:
            pods[pod_name]["Status"] = _merge_pod_status(
                pods[pod_name]["Status"], status
            )

        pods[pod_name]["Containers"].append({"Names": name, "Status": status})

    return list(pods.values())


def pod_inspect(name: str) -> Optional[Dict]:
    """Inspect a 'pod' (primary container in Docker).

    For Docker, we inspect the first container with the pod name pattern.
    """
    container_name = f"{name}-0"
    try:
        proc = _run(["container", "inspect", container_name])
    except subprocess.CalledProcessError:
        return None
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return parsed[0] if isinstance(parsed, list) and parsed else parsed


def stop_pod(name: str, timeout: int = 10) -> None:
    """Stop a 'pod' (all containers matching the pod name pattern)."""
    # List all containers belonging to this pod
    try:
        proc = _run(
            ["ps", "--all", "--filter", f"name={name}-", "--format", "{{.Names}}"]
        )
        container_names = [
            line.strip() for line in proc.stdout.splitlines() if line.strip()
        ]

        for container_name in container_names:
            try:
                _run(
                    ["container", "stop", f"--time={timeout}", container_name],
                    capture=False,
                )
            except subprocess.CalledProcessError:
                pass  # Continue stopping other containers
    except subprocess.CalledProcessError as exc:
        detail = _format_exc_output(exc)
        msg = f"failed to stop pod {name}"
        if detail:
            msg = f"{msg}: {detail}"
        raise DockerError(msg) from exc


def remove_pod(name: str) -> None:
    """Remove a 'pod' (all containers matching the pod name pattern)."""
    try:
        proc = _run(
            ["ps", "--all", "--filter", f"name={name}-", "--format", "{{.Names}}"]
        )
        container_names = [
            line.strip() for line in proc.stdout.splitlines() if line.strip()
        ]

        for container_name in container_names:
            try:
                _run(["container", "rm", "--force", container_name], capture=False)
            except subprocess.CalledProcessError:
                pass  # Continue removing other containers
    except subprocess.CalledProcessError as exc:
        detail = _format_exc_output(exc)
        msg = f"failed to remove pod {name}"
        if detail:
            msg = f"{msg}: {detail}"
        raise DockerError(msg) from exc


def remove_image(image: str) -> None:
    """Remove a container image."""
    try:
        _run(["image", "rm", "--force", image], capture=False)
    except subprocess.CalledProcessError as exc:
        stdout = _format_exc_output(exc)
        if "no such image" not in stdout.lower():
            raise DockerError(f"failed to remove image {image}: {stdout}") from exc


def stream_logs(
    container: str,
    *,
    follow: bool = False,
    tail: Optional[int] = None,
    since: Optional[str] = None,
) -> int:
    args: List[str] = ["logs"]
    if follow:
        args.append("--follow")
    if tail is not None:
        args.extend(["--tail", str(tail)])
    if since:
        args.extend(["--since", since])
    args.append(container)
    proc = subprocess.run(["docker"] + args)
    return proc.returncode


def exec_in_container(
    container: str, command: List[str], **kwargs
) -> subprocess.CompletedProcess[str]:
    """Execute a command inside a running container."""
    if "capture_output" in kwargs:
        kwargs["capture"] = kwargs.pop("capture_output")
    kwargs.pop("text", None)
    args = ["exec", container] + command
    try:
        return _run(args, **kwargs)
    except subprocess.CalledProcessError as exc:
        detail = _format_exc_output(exc)
        msg = f"failed to exec in container {container}"
        if detail:
            msg = f"{msg}: {detail}"
        raise DockerError(msg) from exc


def copy_to_container(src: str, container: str, dest: str) -> None:
    """Copy a file from host to container."""
    try:
        subprocess.run(
            ["docker", "cp", src, f"{container}:{dest}"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() if exc.stderr else ""
        msg = f"failed to copy {src} to container {container}:{dest}"
        if detail:
            msg = f"{msg}: {detail}"
        raise DockerError(msg) from exc


def copy_from_container(container: str, src: str, dest: str) -> None:
    """Copy a file from container to host."""
    try:
        subprocess.run(
            ["docker", "cp", f"{container}:{src}", dest],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() if exc.stderr else ""
        msg = f"failed to copy from container {container}:{src} to {dest}"
        if detail:
            msg = f"{msg}: {detail}"
        raise DockerError(msg) from exc


def container_inspect(name: str) -> Optional[Dict]:
    """Inspect a container and return its configuration."""
    try:
        proc = _run(["container", "inspect", name])
        parsed = json.loads(proc.stdout)
        return parsed[0] if isinstance(parsed, list) and parsed else parsed
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None


def list_containers(filters: Optional[Dict] = None) -> List[Dict]:
    """List containers matching filters."""
    return _ps_json(filters)
