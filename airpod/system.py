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


@dataclass
class ResourceStats:
    cpu_percent: float
    cpu_count: int
    ram_used_gb: float
    ram_total_gb: float
    ram_percent: float
    gpu_name: Optional[str]
    gpu_used_mb: Optional[int]
    gpu_total_mb: Optional[int]
    gpu_percent: Optional[float]


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


def get_gpu_stats() -> Tuple[Optional[str], Optional[int], Optional[int], Optional[float]]:
    """Get GPU memory usage via nvidia-smi. Returns (name, used_mb, total_mb, percent)."""
    if shutil.which("nvidia-smi") is None:
        return None, None, None, None
    
    ok, output = _run_command([
        "nvidia-smi",
        "--query-gpu=name,memory.used,memory.total",
        "--format=csv,noheader,nounits"
    ])
    
    if not ok or not output:
        return None, None, None, None
    
    try:
        lines = output.strip().splitlines()
        if not lines:
            return None, None, None, None
        
        # Take first GPU
        parts = [p.strip() for p in lines[0].split(",")]
        if len(parts) != 3:
            return None, None, None, None
        
        name = parts[0]
        used_mb = int(parts[1])
        total_mb = int(parts[2])
        percent = (used_mb / total_mb * 100.0) if total_mb > 0 else 0.0
        
        return name, used_mb, total_mb, percent
    except (ValueError, IndexError):
        return None, None, None, None


def get_resource_stats() -> ResourceStats:
    """Gather system resource statistics (CPU, RAM, GPU)."""
    try:
        import psutil
    except ImportError:
        # Fallback if psutil not installed
        return ResourceStats(
            cpu_percent=0.0,
            cpu_count=0,
            ram_used_gb=0.0,
            ram_total_gb=0.0,
            ram_percent=0.0,
            gpu_name=None,
            gpu_used_mb=None,
            gpu_total_mb=None,
            gpu_percent=None,
        )
    
    # CPU stats
    cpu_percent = psutil.cpu_percent(interval=0.1)
    cpu_count = psutil.cpu_count(logical=True) or 0
    
    # RAM stats
    mem = psutil.virtual_memory()
    ram_used_gb = mem.used / (1024 ** 3)
    ram_total_gb = mem.total / (1024 ** 3)
    ram_percent = mem.percent
    
    # GPU stats
    gpu_name, gpu_used_mb, gpu_total_mb, gpu_percent = get_gpu_stats()
    
    return ResourceStats(
        cpu_percent=cpu_percent,
        cpu_count=cpu_count,
        ram_used_gb=ram_used_gb,
        ram_total_gb=ram_total_gb,
        ram_percent=ram_percent,
        gpu_name=gpu_name,
        gpu_used_mb=gpu_used_mb,
        gpu_total_mb=gpu_total_mb,
        gpu_percent=gpu_percent,
    )
