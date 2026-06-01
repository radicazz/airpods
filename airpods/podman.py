from __future__ import annotations

import json
import shlex
import subprocess
from typing import Dict, Iterable, List, Optional

from ._container_cli import ContainerCLI
from .logging import console


class PodmanError(RuntimeError):
    pass


_cli = ContainerCLI("podman", PodmanError)

# Shared operations — all implemented once in ContainerCLI.
_run = _cli.run
_format_exc_output = _cli.format_exc_output
volume_exists = _cli.volume_exists
ensure_volume = _cli.ensure_volume
list_volumes = _cli.list_volumes
remove_volume = _cli.remove_volume
pull_image = _cli.pull_image
image_exists = _cli.image_exists
image_size = _cli.image_size
image_size_bytes = _cli.image_size_bytes
get_remote_image_size = _cli.get_remote_image_size
container_exists = _cli.container_exists
container_inspect = _cli.container_inspect
stream_logs = _cli.stream_logs
exec_in_container = _cli.exec_in_container
copy_to_container = _cli.copy_to_container
copy_from_container = _cli.copy_from_container


# ------------------------------------------------------------------
# Podman-specific: real pod management
# ------------------------------------------------------------------


def pod_exists(pod: str) -> bool:
    try:
        _run(["pod", "inspect", pod])
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
    # Port mappings are not used with host networking; containers bind directly to host ports.
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
    _cli.remove_image(image, not_found_marker="image not known")


def list_containers(filters: Optional[Dict] = None) -> List[Dict]:
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


# ------------------------------------------------------------------
# Podman-specific: run_container attaches to pod (not host network)
# ------------------------------------------------------------------


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

    if existed:
        try:
            proc = _run(["container", "inspect", name, "--format", "{{.State.Status}}"])
            if proc.stdout.strip() == "running":
                return True
        except subprocess.CalledProcessError:
            pass

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
