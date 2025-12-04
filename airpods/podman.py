from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
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
    if network_aliases:
        for alias in network_aliases:
            args.extend(["--network-alias", alias])
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
