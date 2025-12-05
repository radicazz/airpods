from __future__ import annotations

import json
import shlex
import subprocess
from typing import Dict, Iterable, List, Optional

from .logging import console


class PodmanError(RuntimeError):
    pass


def _run(
    args: List[str], capture: bool = True, check: bool = True
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


def network_exists(name: str) -> bool:
    try:
        _run(["network", "inspect", name])
        return True
    except subprocess.CalledProcessError:
        return False


def ensure_network(
    name: str,
    *,
    driver: str = "bridge",
    subnet: str | None = None,
    gateway: str | None = None,
    dns_servers: list[str] | None = None,
    ipv6: bool = False,
    internal: bool = False,
) -> bool:
    if network_exists(name):
        return False
    args = ["network", "create"]
    args.extend(["--driver", driver])
    if subnet:
        args.extend(["--subnet", subnet])
    if gateway:
        args.extend(["--gateway", gateway])
    if dns_servers:
        for dns in dns_servers:
            args.extend(["--dns", dns])
    if ipv6:
        args.append("--ipv6")
    if internal:
        args.append("--internal")
    args.append(name)
    try:
        _run(args, capture=False)
    except subprocess.CalledProcessError as exc:
        detail = _format_exc_output(exc)
        msg = f"failed to create network {name}"
        if detail:
            msg = f"{msg}: {detail}"
        raise PodmanError(msg) from exc
    return True


def pull_image(image: str) -> None:
    try:
        _run(["pull", image], capture=False)
    except subprocess.CalledProcessError as exc:
        detail = _format_exc_output(exc)
        msg = f"failed to pull image {image}"
        if detail:
            msg = f"{msg}: {detail}"
        raise PodmanError(msg) from exc


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
    pod: str, ports: Iterable[tuple[int, int]], network: str = "airpods_network"
) -> bool:
    if pod_exists(pod):
        return False
    args = ["pod", "create", "--name", pod, "--network", network]
    for host, container in ports:
        args.extend(["-p", f"{host}:{container}"])
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
    network_aliases: List[str] | None = None,
    gpu: bool = False,
    restart_policy: str = "unless-stopped",
    gpu_device_flag: Optional[str] = None,
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
        "--pod",
        pod,
        "--restart",
        restart_policy,
    ]
    for key, val in env.items():
        args.extend(["-e", f"{key}={val}"])
    for volume_name, dest in volumes:
        args.extend(["-v", f"{volume_name}:{dest}"])
    if gpu and gpu_device_flag:
        args.extend(shlex.split(gpu_device_flag))
    args.append(image)
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


def remove_network(name: str) -> None:
    """Remove a Podman network."""
    try:
        _run(["network", "rm", "--force", name], capture=False)
    except subprocess.CalledProcessError as exc:
        detail = _format_exc_output(exc)
        msg = f"failed to remove network {name}"
        if detail:
            msg = f"{msg}: {detail}"
        raise PodmanError(msg) from exc


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
