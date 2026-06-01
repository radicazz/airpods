"""Shared subprocess helpers for the Docker and Podman CLI wrappers."""

from __future__ import annotations

import json
import subprocess
from typing import Dict, List, Optional, Type


class ContainerCLI:
    """Parameterized low-level helper shared between docker.py and podman.py.

    Every public method maps directly to a container-runtime CLI operation.
    Docker-specific and Podman-specific divergences (pod management, ps format,
    etc.) stay in the respective modules.
    """

    def __init__(self, cmd: str, error_cls: Type[RuntimeError]) -> None:
        self._cmd = [cmd]
        self._error = error_cls

    # ------------------------------------------------------------------
    # Low-level runner
    # ------------------------------------------------------------------

    def run(
        self,
        args: List[str],
        capture: bool = True,
        check: bool = True,
        timeout: Optional[float] = None,
    ) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            self._cmd + args,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=check,
            timeout=timeout,
        )
        return proc

    @staticmethod
    def format_exc_output(exc: subprocess.CalledProcessError) -> str:
        output = getattr(exc, "stdout", None) or getattr(exc, "output", None)
        return output.strip() if output else ""

    # ------------------------------------------------------------------
    # Volumes
    # ------------------------------------------------------------------

    def volume_exists(self, name: str) -> bool:
        try:
            self.run(["volume", "inspect", name])
            return True
        except subprocess.CalledProcessError:
            return False

    def ensure_volume(self, name: str) -> bool:
        if self.volume_exists(name):
            return False
        try:
            self.run(["volume", "create", name], capture=False)
        except subprocess.CalledProcessError as exc:
            detail = self.format_exc_output(exc)
            msg = f"failed to create volume {name}"
            if detail:
                msg = f"{msg}: {detail}"
            raise self._error(msg) from exc
        return True

    def list_volumes(self) -> List[str]:
        try:
            proc = self.run(["volume", "ls", "--format", "{{.Name}}"])
            return [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        except subprocess.CalledProcessError:
            return []

    def remove_volume(self, name: str) -> None:
        try:
            self.run(["volume", "rm", "--force", name], capture=False)
        except subprocess.CalledProcessError as exc:
            detail = self.format_exc_output(exc)
            msg = f"failed to remove volume {name}"
            if detail:
                msg = f"{msg}: {detail}"
            raise self._error(msg) from exc

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------

    def pull_image(self, image: str) -> None:
        try:
            self.run(["pull", image], capture=False)
        except subprocess.CalledProcessError as exc:
            detail = self.format_exc_output(exc)
            msg = f"failed to pull image {image}"
            if detail:
                msg = f"{msg}: {detail}"
            raise self._error(msg) from exc

    def image_exists(self, image: str) -> bool:
        try:
            self.run(["image", "inspect", image])
            return True
        except subprocess.CalledProcessError:
            return False

    def image_size(self, image: str) -> Optional[str]:
        try:
            proc = self.run(["image", "inspect", image, "--format", "{{.Size}}"])
            size_bytes = int(proc.stdout.strip())
            for unit in ["B", "KB", "MB", "GB"]:
                if size_bytes < 1024.0:
                    return f"{size_bytes:.1f}{unit}"
                size_bytes /= 1024.0
            return f"{size_bytes:.1f}TB"
        except (subprocess.CalledProcessError, ValueError):
            return None

    def image_size_bytes(self, image: str) -> Optional[int]:
        try:
            proc = self.run(["image", "inspect", image, "--format", "{{.Size}}"])
            return int(proc.stdout.strip())
        except (subprocess.CalledProcessError, ValueError):
            return None

    def get_remote_image_size(self, image: str) -> Optional[int]:
        if self.image_exists(image):
            return self.image_size_bytes(image)
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
                if "Size" in data:
                    return int(data["Size"])
        except (OSError, json.JSONDecodeError, ValueError, KeyError):
            pass
        return None

    def remove_image(self, image: str, not_found_marker: str = "no such image") -> None:
        try:
            self.run(["image", "rm", "--force", image], capture=False)
        except subprocess.CalledProcessError as exc:
            stdout = self.format_exc_output(exc)
            if not_found_marker not in stdout.lower():
                raise self._error(f"failed to remove image {image}: {stdout}") from exc

    # ------------------------------------------------------------------
    # Containers
    # ------------------------------------------------------------------

    def container_exists(self, name: str) -> bool:
        try:
            self.run(["container", "inspect", name])
            return True
        except subprocess.CalledProcessError:
            return False

    def container_inspect(self, name: str) -> Optional[Dict]:
        try:
            proc = self.run(["container", "inspect", name])
            parsed = json.loads(proc.stdout)
            return parsed[0] if isinstance(parsed, list) and parsed else parsed
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            return None

    def stream_logs(
        self,
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
        proc = subprocess.run(self._cmd + args)
        return proc.returncode

    def exec_in_container(
        self, container: str, command: List[str], **kwargs
    ) -> subprocess.CompletedProcess[str]:
        if "capture_output" in kwargs:
            kwargs["capture"] = kwargs.pop("capture_output")
        kwargs.pop("text", None)
        args = ["exec", container] + command
        try:
            return self.run(args, **kwargs)
        except subprocess.CalledProcessError as exc:
            detail = self.format_exc_output(exc)
            msg = f"failed to exec in container {container}"
            if detail:
                msg = f"{msg}: {detail}"
            raise self._error(msg) from exc

    def copy_to_container(self, src: str, container: str, dest: str) -> None:
        try:
            subprocess.run(
                self._cmd + ["cp", src, f"{container}:{dest}"],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() if exc.stderr else ""
            msg = f"failed to copy {src} to container {container}:{dest}"
            if detail:
                msg = f"{msg}: {detail}"
            raise self._error(msg) from exc

    def copy_from_container(self, container: str, src: str, dest: str) -> None:
        try:
            subprocess.run(
                self._cmd + ["cp", f"{container}:{src}", dest],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() if exc.stderr else ""
            msg = f"failed to copy from container {container}:{src} to {dest}"
            if detail:
                msg = f"{msg}: {detail}"
            raise self._error(msg) from exc
