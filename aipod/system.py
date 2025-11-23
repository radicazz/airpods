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


def check_dependency(name: str, version_args: Optional[List[str]] = None) -> CheckResult:
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
    ok, output = _run_command(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"])
    if not ok:
        return False, "nvidia-smi failed"
    gpu_names = [line.strip() for line in output.splitlines() if line.strip()]
    if not gpu_names:
        return False, "no GPUs detected"
    return True, ", ".join(gpu_names)
