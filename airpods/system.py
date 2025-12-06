from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


def _run_command(args: List[str]) -> Tuple[bool, str]:
    try:
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        output = exc.output if isinstance(exc, subprocess.CalledProcessError) else ""
        return False, (output or str(exc))
    return True, proc.stdout.strip()


def check_dependency(
    name: str, version_args: Optional[List[str]] = None
) -> CheckResult:
    if shutil.which(name) is None:
        return CheckResult(name=name, ok=False, detail="not found in PATH")
    if version_args:
        ok, output = _run_command([name] + version_args)
        return CheckResult(name=name, ok=ok, detail=output if ok else "unable to run")
    return CheckResult(name=name, ok=True, detail="available")


def detect_gpu() -> Tuple[bool, str]:
    """Detect NVIDIA GPU via nvidia-smi; fail softly."""
    if shutil.which("nvidia-smi") is None:
        return False, "nvidia-smi not found"
    ok, output = _run_command(
        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"]
    )
    if not ok:
        return False, "nvidia-smi failed"
    gpu_names = [line.strip() for line in output.splitlines() if line.strip()]
    if not gpu_names:
        return False, "no GPUs detected"
    return True, ", ".join(gpu_names)


def detect_cuda_compute_capability() -> Tuple[bool, str, Optional[Tuple[int, int]]]:
    """Detect NVIDIA GPU compute capability via nvidia-smi; fail softly.

    Returns:
        (has_gpu, gpu_name, compute_capability)

        has_gpu: True if GPU detected and query succeeded
        gpu_name: Name of the first GPU, or error message if failed
        compute_capability: (major, minor) tuple like (7, 5) for compute 7.5, or None if failed
    """
    if shutil.which("nvidia-smi") is None:
        return False, "nvidia-smi not found", None

    # Query both name and compute capability
    ok, output = _run_command(
        ["nvidia-smi", "--query-gpu=name,compute_cap", "--format=csv,noheader,nounits"]
    )
    if not ok:
        return False, "nvidia-smi failed", None

    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return False, "no GPUs detected", None

    # Parse first GPU line: "NVIDIA GeForce GTX 1650, 7.5"
    try:
        gpu_name, compute_cap_str = lines[0].split(", ", 1)
        gpu_name = gpu_name.strip()
        compute_cap_str = compute_cap_str.strip()

        # Parse compute capability like "7.5" into (7, 5)
        major_str, minor_str = compute_cap_str.split(".", 1)
        major = int(major_str)
        minor = int(minor_str)

        return True, gpu_name, (major, minor)
    except (ValueError, IndexError) as exc:
        # Fallback to just GPU name if compute capability parsing fails
        gpu_name = lines[0].split(",")[0].strip() if "," in lines[0] else lines[0]
        return False, f"{gpu_name} (compute capability parse failed: {exc})", None
