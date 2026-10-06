"""Helpers for managing ComfyUI custom nodes."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from airpods.configuration import get_config
from airpods.configuration.schema import CustomNodeInstall
from airpods.files import managed_path
from airpods.logging import console
from airpods.plugins import get_comfyui_plugins_target_dir


@dataclass(frozen=True)
class CustomNodeResult:
    name: str
    dest: Path
    action: str
    detail: str | None = None


@dataclass(frozen=True)
class CustomNodeRequirement:
    name: str
    host_path: Path
    container_path: str
    marker_path: Path


def _read_marker(marker: Path) -> dict[str, str]:
    try:
        content = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return {}
    if not content:
        return {}
    data: dict[str, str] = {}
    for line in content.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            data[key] = value
    return data


def _write_marker(marker: Path, *, mode: str, container_id: str | None = None) -> None:
    lines = [f"mode={mode}"]
    if container_id:
        lines.append(f"container_id={container_id}")
    marker.write_text("\n".join(lines) + "\n", encoding="utf-8")


def get_custom_node_specs() -> list[CustomNodeInstall]:
    """Return enabled custom node specs from config."""
    config = get_config()
    service = config.services.get("comfyui")
    if not service or not service.enabled:
        return []
    custom_nodes = service.custom_nodes
    if not custom_nodes:
        return []
    return [node for node in custom_nodes.install if node.enabled]


def custom_nodes_target_dir() -> Path:
    """Return the host-side custom nodes volume directory."""
    return get_comfyui_plugins_target_dir()


def node_destination(
    node: CustomNodeInstall, *, target_root: Path | None = None
) -> Path:
    """Resolve the on-disk destination path for a custom node."""
    root = target_root or custom_nodes_target_dir()
    dest = managed_path(root, node.name)

    if node.path:
        source = Path(node.path)
        if source.is_file():
            suffix = source.suffix or ".py"
            if dest.suffix != suffix:
                dest = dest.with_suffix(suffix)

    return managed_path(root, dest.name)


def custom_nodes_keep_entries(nodes: Iterable[CustomNodeInstall]) -> set[str]:
    """Return relative paths in custom_nodes that should not be pruned."""
    root = custom_nodes_target_dir()
    keep: set[str] = set()
    for node in nodes:
        dest = node_destination(node, target_root=root)
        try:
            rel = dest.relative_to(root)
        except ValueError:
            continue
        keep.add(rel.as_posix())
    return keep


def _dir_mtime(path: Path) -> float:
    latest = path.stat().st_mtime
    for item in path.rglob("*"):
        if item.is_file():
            latest = max(latest, item.stat().st_mtime)
    return latest


def _should_copy_tree(src: Path, dest: Path) -> bool:
    if not dest.exists():
        return True
    return _dir_mtime(src) > _dir_mtime(dest)


def _copy_tree(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".git"))


def _copy_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def _git_available() -> bool:
    return shutil.which("git") is not None


def prepare_custom_nodes(
    nodes: Iterable[CustomNodeInstall], *, verbose: bool = False
) -> list[CustomNodeResult]:
    """Ensure configured custom nodes exist in the custom_nodes volume."""
    target_root = custom_nodes_target_dir()
    target_root.mkdir(parents=True, exist_ok=True)

    results: list[CustomNodeResult] = []

    for node in nodes:
        dest = node_destination(node, target_root=target_root)

        if node.path:
            source = Path(node.path)
            if source.is_dir():
                if _should_copy_tree(source, dest):
                    _copy_tree(source, dest)
                    results.append(
                        CustomNodeResult(node.name, dest, "copied", str(source))
                    )
                else:
                    results.append(
                        CustomNodeResult(node.name, dest, "skipped", "up-to-date")
                    )
                continue

            if source.is_file():
                if not dest.exists() or source.stat().st_mtime > dest.stat().st_mtime:
                    _copy_file(source, dest)
                    results.append(
                        CustomNodeResult(node.name, dest, "copied", str(source))
                    )
                else:
                    results.append(
                        CustomNodeResult(node.name, dest, "skipped", "up-to-date")
                    )
                continue

            results.append(
                CustomNodeResult(node.name, dest, "error", f"path not found: {source}")
            )
            continue

        if node.repo:
            if dest.exists():
                results.append(
                    CustomNodeResult(node.name, dest, "skipped", "already present")
                )
                continue

            if not _git_available():
                results.append(
                    CustomNodeResult(node.name, dest, "error", "git not found on PATH")
                )
                continue

            try:
                subprocess.run(
                    ["git", "clone", node.repo, str(dest)],
                    check=True,
                    capture_output=not verbose,
                    text=True,
                )
                if node.ref:
                    subprocess.run(
                        ["git", "-C", str(dest), "checkout", node.ref],
                        check=True,
                        capture_output=not verbose,
                        text=True,
                    )
                results.append(
                    CustomNodeResult(
                        node.name,
                        dest,
                        "cloned",
                        node.ref or "default",
                    )
                )
            except subprocess.CalledProcessError as exc:
                detail = exc.stderr.strip() if exc.stderr else str(exc)
                results.append(CustomNodeResult(node.name, dest, "error", detail))

    return results


def collect_requirements(
    nodes: Iterable[CustomNodeInstall],
    *,
    container_custom_nodes_dir: str,
    container_id: str | None = None,
) -> list[CustomNodeRequirement]:
    """Collect requirement files for configured nodes (host + container paths)."""
    requirements: list[CustomNodeRequirement] = []
    target_root = custom_nodes_target_dir()
    container_root = Path(container_custom_nodes_dir)

    for node in nodes:
        req = node.requirements
        if not req:
            continue
        if node.path and Path(node.path).is_file():
            continue

        host_req = managed_path(managed_path(target_root, node.name), req)

        if not host_req.exists():
            console.print(
                f"[warn]Custom node requirements not found for {node.name}: {host_req}[/]"
            )
            continue

        marker = host_req.parent / ".airpods-requirements.installed"
        if marker.exists() and marker.stat().st_mtime >= host_req.stat().st_mtime:
            meta = _read_marker(marker)
            if meta.get("mode") == "user":
                if container_id and meta.get("container_id") == container_id:
                    continue
            else:
                continue

        try:
            rel = host_req.relative_to(target_root)
        except ValueError:
            console.print(
                f"[warn]Requirements file is outside custom_nodes volume for {node.name}: {host_req}[/]"
            )
            continue

        container_req = (container_root / rel).as_posix()
        requirements.append(
            CustomNodeRequirement(node.name, host_req, container_req, marker)
        )

    return requirements


def _is_permission_error(detail: str) -> bool:
    """Check if error is due to permission denied."""
    lowered = detail.lower()
    return (
        "permission denied" in lowered
        or "errno 13" in lowered
        or "read-only file system" in lowered
    )


def _is_externally_managed_error(detail: str) -> bool:
    """Check if error is due to externally managed environment."""
    lowered = detail.lower()
    return (
        "externally-managed-environment" in lowered or "externally managed" in lowered
    )


def install_requirements(
    *,
    runtime,
    container_name: str,
    requirements: Iterable[CustomNodeRequirement],
    target_dir: str,
    container_id: str | None = None,
) -> list[CustomNodeResult]:
    """Install requirements inside a running container."""
    results: list[CustomNodeResult] = []
    install_target = target_dir.rstrip("/")

    for req in requirements:

        def run_pip(args: list[str]) -> subprocess.CompletedProcess:
            return runtime.exec_in_container(
                container_name,
                args,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )

        base_args = [
            "python3",
            "-m",
            "pip",
            "install",
            "-r",
            req.container_path,
            "--target",
            install_target,
            "--upgrade",
        ]

        try:
            result = run_pip(base_args)
        except Exception as exc:  # pragma: no cover - runtime-specific failures
            results.append(CustomNodeResult(req.name, req.host_path, "error", str(exc)))
            continue

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            if _is_externally_managed_error(detail):
                result = run_pip(base_args + ["--break-system-packages"])
                if result.returncode == 0:
                    req.marker_path.parent.mkdir(parents=True, exist_ok=True)
                    _write_marker(req.marker_path, mode="target")
                    results.append(
                        CustomNodeResult(req.name, req.host_path, "installed")
                    )
                    continue
                detail = (result.stderr or result.stdout or "").strip()

            if _is_permission_error(detail):
                user_args = [
                    "python3",
                    "-m",
                    "pip",
                    "install",
                    "-r",
                    req.container_path,
                    "--user",
                    "--upgrade",
                ]
                fallback = run_pip(user_args)
                if fallback.returncode != 0:
                    fallback_detail = (fallback.stderr or fallback.stdout or "").strip()
                    if _is_externally_managed_error(fallback_detail):
                        fallback = run_pip(user_args + ["--break-system-packages"])
                        if fallback.returncode == 0:
                            req.marker_path.parent.mkdir(parents=True, exist_ok=True)
                            _write_marker(
                                req.marker_path, mode="user", container_id=container_id
                            )
                            results.append(
                                CustomNodeResult(
                                    req.name, req.host_path, "installed-user"
                                )
                            )
                            continue
                        fallback_detail = (
                            fallback.stderr or fallback.stdout or ""
                        ).strip()
                    results.append(
                        CustomNodeResult(
                            req.name, req.host_path, "error", fallback_detail
                        )
                    )
                else:
                    req.marker_path.parent.mkdir(parents=True, exist_ok=True)
                    _write_marker(
                        req.marker_path, mode="user", container_id=container_id
                    )
                    results.append(
                        CustomNodeResult(req.name, req.host_path, "installed-user")
                    )
            else:
                results.append(
                    CustomNodeResult(req.name, req.host_path, "error", detail)
                )
        else:
            req.marker_path.parent.mkdir(parents=True, exist_ok=True)
            _write_marker(req.marker_path, mode="target")
            results.append(CustomNodeResult(req.name, req.host_path, "installed"))

    return results
