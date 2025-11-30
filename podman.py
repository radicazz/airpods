from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .logging import console


class PodmanError(RuntimeError):
    pass


def _run(args: List[str], capture: bool = True, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = ["podman"] + args
    proc = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        check=check,
    )
    return proc


def ensure_directory(path: Path, mode: int = 0o755) -> None:
    """Create a directory with proper permissions for bind mounts."""
    import os
    import stat
    
    if not path.exists():
        try:
            path.mkdir(parents=True, exist_ok=True, mode=mode)
        except OSError as exc:
            raise PodmanError(f"failed to create directory {path}: {exc}") from exc
    
    # Ensure directory is owned by current user (fix for podman user namespace issues)
    try:
        current_uid = os.getuid()
        current_gid = os.getgid()
        stat_info = path.stat()
        
        # Only change ownership if it's currently root (0:0) and we're not root
        if stat_info.st_uid == 0 and stat_info.st_gid == 0 and current_uid != 0:
            try:
                # Try to change ownership - this will work if the directory is empty
                # or if we have sudo access configured for chown
                import subprocess
                subprocess.run(
                    ["chown", f"{current_uid}:{current_gid}", str(path)],
                    check=True,
                    capture_output=True
                )
            except (subprocess.CalledProcessError, FileNotFoundError):
                # If chown fails (no sudo or not installed), try via Path
                try:
                    os.chown(path, current_uid, current_gid)
                except PermissionError:
                    # Last resort: inform user
                    console.print(f"[warn]Directory {path} is owned by root. Run: chown -R {current_uid}:{current_gid} {path}[/]")
    except Exception:
        # Don't fail if we can't check/fix ownership
        pass


def pull_image(image: str) -> None:
    try:
        _run(["pull", image], capture=False)
    except subprocess.CalledProcessError as exc:
        raise PodmanError(f"failed to pull image {image}: {exc}") from exc


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


def ensure_pod(pod: str, ports: Iterable[tuple[int, int]]) -> None:
    if pod_exists(pod):
        return
    args = ["pod", "create", "--name", pod]
    for host, container in ports:
        args.extend(["-p", f"{host}:{container}"])
    try:
        _run(args, capture=True)
    except subprocess.CalledProcessError as exc:
        raise PodmanError(f"failed to create pod {pod}: {exc}") from exc


def run_container(
    *,
    pod: str,
    name: str,
    image: str,
    env: Dict[str, str],
    volumes: Iterable[tuple[str, str]],
    gpu: bool = False,
    command: Optional[List[str]] = None,
    userns_keep_id: bool = False,
    volume_opts: Optional[str] = None,
) -> None:
    args: List[str] = [
        "run",
        "--detach",
        "--replace",
        "--name",
        name,
        "--pod",
        pod,
        "--restart",
        "unless-stopped",
    ]
    if userns_keep_id:
        args.append("--userns=keep-id")
    for key, val in env.items():
        args.extend(["-e", f"{key}={val}"])
    for volume_name, dest in volumes:
        if volume_opts:
            args.extend(["-v", f"{volume_name}:{dest}:{volume_opts}"])
        else:
            args.extend(["-v", f"{volume_name}:{dest}"])
    if gpu:
        args.extend(["--device", "nvidia.com/gpu=all"])
    args.append(image)
    if command:
        args.extend(command)
    try:
        _run(args, capture=True)
    except subprocess.CalledProcessError as exc:
        raise PodmanError(f"failed to start container {name}: {exc}") from exc


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
        _run(["pod", "stop", "--ignore", f"--time={timeout}", name], capture=True)
    except subprocess.CalledProcessError as exc:
        raise PodmanError(f"failed to stop pod {name}: {exc}") from exc


def remove_pod(name: str) -> None:
    try:
        _run(["pod", "rm", "--force", "--ignore", name], capture=True)
    except subprocess.CalledProcessError as exc:
        raise PodmanError(f"failed to remove pod {name}: {exc}") from exc


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
