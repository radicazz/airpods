from __future__ import annotations

import json
import logging
import shlex
import subprocess
from typing import Dict, Iterable, List, Optional

from ._container_cli import ContainerCLI
from .logging import console

log = logging.getLogger(__name__)


class DockerError(RuntimeError):
    pass


_cli = ContainerCLI("docker", DockerError)

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
# Docker-specific: ps parsing (Docker lacks Podman's --format json)
# ------------------------------------------------------------------


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
    if value == "running" or value.startswith("Up"):
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


# ------------------------------------------------------------------
# Docker-specific: pod simulation (Docker has no real pods)
# ------------------------------------------------------------------


def pod_exists(pod: str) -> bool:
    return container_exists(f"{pod}-0")


def ensure_pod(
    pod: str,
    ports: Iterable[tuple[int, int]],
    userns_mode: Optional[str] = None,
) -> bool:
    # Docker has no pod concept; containers bind to host ports directly.
    return False


def pod_status() -> List[Dict]:
    containers = _ps_json()

    pods: Dict[str, Dict] = {}
    for container in containers:
        name = container.get("Names", "")
        if not name:
            continue

        raw_status = container.get("State") or container.get("Status") or ""
        status = _normalize_container_status(str(raw_status))
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
            except subprocess.CalledProcessError as exc:
                log.warning(
                    "failed to stop container %s: %s",
                    container_name,
                    _format_exc_output(exc),
                )
    except subprocess.CalledProcessError as exc:
        detail = _format_exc_output(exc)
        msg = f"failed to stop pod {name}"
        if detail:
            msg = f"{msg}: {detail}"
        raise DockerError(msg) from exc


def remove_pod(name: str) -> None:
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
            except subprocess.CalledProcessError as exc:
                log.warning(
                    "failed to remove container %s: %s",
                    container_name,
                    _format_exc_output(exc),
                )
    except subprocess.CalledProcessError as exc:
        detail = _format_exc_output(exc)
        msg = f"failed to remove pod {name}"
        if detail:
            msg = f"{msg}: {detail}"
        raise DockerError(msg) from exc


def remove_image(image: str) -> None:
    _cli.remove_image(image, not_found_marker="no such image")


def list_containers(filters: Optional[Dict] = None) -> List[Dict]:
    return _ps_json(filters)


# ------------------------------------------------------------------
# Docker-specific: run_container uses host networking (no --pod)
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

    if existed:
        try:
            _run(["container", "stop", name], check=False)
            _run(["container", "rm", name], check=False)
        except subprocess.CalledProcessError as exc:
            log.warning(
                "failed to remove existing container %s: %s",
                name,
                _format_exc_output(exc),
            )

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
        "host",
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
