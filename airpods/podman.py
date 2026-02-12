from __future__ import annotations

import json
import shlex
import subprocess
from typing import Dict, Iterable, List, Optional

from .logging import console


class PodmanError(RuntimeError):
    pass


def _run(
    args: List[str],
    capture: bool = True,
    check: bool = True,
    timeout: Optional[float] = None,
) -> subprocess.CompletedProcess[str]:
    """Run a podman command and return the completed process.

    Output is always captured so Rich spinners stay clean. Callers can read
    proc.stdout when needed.
    """
    cmd = ["podman"] + args
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
        raise PodmanError(msg) from exc
    return True


def list_volumes() -> List[str]:
    """List all Podman volumes matching airpods pattern."""
    try:
        proc = _run(["volume", "ls", "--format", "{{.Name}}"])
        return [
            line.strip()
            for line in proc.stdout.splitlines()
            if line.strip().startswith("airpods_")
        ]
    except subprocess.CalledProcessError:
        return []


def remove_volume(name: str) -> None:
    """Remove a Podman volume by name."""
    try:
        _run(["volume", "rm", "--force", name], capture=False)
    except subprocess.CalledProcessError as exc:
        detail = _format_exc_output(exc)
        msg = f"failed to remove volume {name}"
        if detail:
            msg = f"{msg}: {detail}"
        raise PodmanError(msg) from exc


def pull_image(image: str) -> None:
    try:
        _run(["pull", image], capture=False)
    except subprocess.CalledProcessError as exc:
        detail = _format_exc_output(exc)
        msg = f"failed to pull image {image}"
        if detail:
            msg = f"{msg}: {detail}"
        raise PodmanError(msg) from exc


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
    try:
        _run(["pod", "inspect", pod])
        return True
    except subprocess.CalledProcessError:
        return False


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
    if pod_exists(pod):
        return False
    # Port mappings are not used with host networking; containers bind directly to host ports
    args = ["pod", "create", "--name", pod, "--network", "host"]
    if userns_mode:
        args.extend(["--userns", userns_mode])
    try:
        _run(args, capture=False)
    except subprocess.CalledProcessError as exc:
        detail = _format_exc_output(exc)
        msg = f"failed to create pod {pod}"
        if detail:
            msg = f"{msg}: {detail}"
        raise PodmanError(msg) from exc
    return True


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
    # The secret and other env vars are already baked into the container
    if existed:
        try:
            proc = _run(["container", "inspect", name, "--format", "{{.State.Status}}"])
            status = proc.stdout.strip()
            if status == "running":
                return True  # Container already running, no need to replace
        except subprocess.CalledProcessError:
            pass  # Fall through to replace

    args: List[str] = [
        "run",
        "--detach",
        "--replace",
        "--name",
        name,
        "--restart",
        restart_policy,
        "--pids-limit",
        str(pids_limit),
        "--pod",
        pod,
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
        raise PodmanError(msg) from exc
    return existed


def pod_status() -> List[Dict]:
    proc = _run(["pod", "ps", "--format", "json"])
    try:
        return json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        console.print("[warn]could not parse podman pod ps output[/]")
        return []


def pod_inspect(name: str) -> Optional[Dict]:
    try:
        proc = _run(["pod", "inspect", name])
    except subprocess.CalledProcessError:
        return None
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return parsed[0] if isinstance(parsed, list) and parsed else parsed


def stop_pod(name: str, timeout: int = 10) -> None:
    try:
        _run(["pod", "stop", "--ignore", f"--time={timeout}", name], capture=False)
    except subprocess.CalledProcessError as exc:
        detail = _format_exc_output(exc)
        msg = f"failed to stop pod {name}"
        if detail:
            msg = f"{msg}: {detail}"
        raise PodmanError(msg) from exc


def remove_pod(name: str) -> None:
    try:
        _run(["pod", "rm", "--force", "--ignore", name], capture=False)
    except subprocess.CalledProcessError as exc:
        detail = _format_exc_output(exc)
        msg = f"failed to remove pod {name}"
        if detail:
            msg = f"{msg}: {detail}"
        raise PodmanError(msg) from exc


def remove_image(image: str) -> None:
    """Remove a container image."""
    try:
        _run(["image", "rm", "--force", image], capture=False)
    except subprocess.CalledProcessError as exc:
        stdout = _format_exc_output(exc)
        if "image not known" not in stdout.lower():
            raise PodmanError(f"failed to remove image {image}: {stdout}") from exc


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
    proc = subprocess.run(["podman"] + args)
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
        raise PodmanError(msg) from exc


def copy_to_container(src: str, container: str, dest: str) -> None:
    """Copy a file from host to container."""
    try:
        subprocess.run(
            ["podman", "cp", src, f"{container}:{dest}"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() if exc.stderr else ""
        msg = f"failed to copy {src} to container {container}:{dest}"
        if detail:
            msg = f"{msg}: {detail}"
        raise PodmanError(msg) from exc


def copy_from_container(container: str, src: str, dest: str) -> None:
    """Copy a file from container to host."""
    try:
        subprocess.run(
            ["podman", "cp", f"{container}:{src}", dest],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() if exc.stderr else ""
        msg = f"failed to copy from container {container}:{src} to {dest}"
        if detail:
            msg = f"{msg}: {detail}"
        raise PodmanError(msg) from exc


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
    args = ["ps", "--all", "--format", "json"]
    if filters:
        for key, value in filters.items():
            args.extend(["--filter", f"{key}={value}"])

    try:
        proc = _run(args)
        containers = json.loads(proc.stdout or "[]")
        return containers if isinstance(containers, list) else []
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return []
