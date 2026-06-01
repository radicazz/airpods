"""Pydantic models describing the configuration schema."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Covers https://, git://, git@host:, and ssh:// style git URLs.
_GIT_URL_RE = re.compile(
    r"^(https?://|git://|git@|ssh://git@|file://|[\w.+-]+@[\w.-]+:)"
)


def _is_valid_git_url(url: str) -> bool:
    return bool(_GIT_URL_RE.match(url))


class MetaConfig(BaseModel):
    version: str = "1.0"


class RuntimeConfig(BaseModel):
    prefer: Literal["auto", "podman", "docker"] = "auto"
    gpu_device_flag: str = "auto"
    restart_policy: Literal["no", "on-failure", "always", "unless-stopped"] = (
        "unless-stopped"
    )
    cuda_version: Literal["auto", "cu118", "cu126", "cu128", "cu130", "cpu"] = "auto"
    comfyui_provider: Literal["auto", "yanwk", "mmartial"] = "auto"


class CLIConfig(BaseModel):
    stop_timeout: int = Field(default=10, ge=1, le=300)
    log_lines: int = Field(default=200, ge=1, le=10000)
    ping_timeout: float = Field(default=2.0, ge=0.1, le=60.0)
    startup_timeout: int = Field(default=120, ge=10, le=600)
    startup_check_interval: float = Field(default=2.0, ge=0.5, le=10.0)
    max_concurrent_pulls: int = Field(default=3, ge=1, le=10)
    plugin_owner: Literal["auto", "admin", "airpods"] = "airpods"
    auto_confirm: bool = False
    verbose: bool = False
    debug: bool = False


class DependenciesConfig(BaseModel):
    required: List[str] = Field(default_factory=lambda: ["uv"])
    runtime_deps: Dict[str, List[str]] = Field(
        default_factory=lambda: {
            "podman": ["podman", "podman-compose"],
            "docker": ["docker", "docker-compose"],
        }
    )
    optional: List[str] = Field(default_factory=lambda: ["nvidia-smi"])
    skip_checks: bool = False


class PortMapping(BaseModel):
    host: int = Field(ge=1, le=65535)
    container: int = Field(ge=1, le=65535)


class VolumeMount(BaseModel):
    source: str
    target: str

    @field_validator("target")
    @classmethod
    def validate_target(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("Container mount path must be absolute")
        return value


class GPUConfig(BaseModel):
    enabled: bool = True
    force_cpu: bool = False


class HealthConfig(BaseModel):
    path: Optional[str] = None
    expected_status: Tuple[int, int] = (200, 299)

    @field_validator("expected_status", mode="before")
    @classmethod
    def normalize_status(
        cls, value: Tuple[int, int] | List[int] | None
    ) -> Tuple[int, int]:
        if value is None:
            return (200, 299)
        if isinstance(value, tuple):
            start, end = value
        elif isinstance(value, list):
            if len(value) != 2:
                raise ValueError("expected_status must contain two integers")
            start, end = value
        else:
            raise ValueError("expected_status must be a tuple/list of two integers")
        if start > end:
            raise ValueError("Status range start must be <= end")
        if not (100 <= start <= 599 and 100 <= end <= 599):
            raise ValueError("HTTP status codes must be in 100-599 range")
        return (start, end)


class ResourceLimits(BaseModel):
    memory: Optional[str] = None
    cpus: Optional[str] = None

    @field_validator("memory")
    @classmethod
    def validate_memory(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        import re

        if not re.match(r"^\d+[kKmMgG]$", value):
            raise ValueError("Memory must look like '512m' or '4g'")
        return value


CommandArgScalar = Union[str, int, float, bool]
CommandArgValue = Union[CommandArgScalar, List[Union[str, int, float]]]


class CustomNodeInstall(BaseModel):
    name: str
    repo: Optional[str] = None
    path: Optional[str] = None
    ref: Optional[str] = None
    requirements: Optional[str] = "requirements.txt"
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("custom node name cannot be empty")
        return cleaned

    @field_validator("repo")
    @classmethod
    def normalize_repo(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if cleaned and not _is_valid_git_url(cleaned):
            raise ValueError(
                f"custom node repo must be a valid git URL (https://, git@, ssh://, etc.): {cleaned!r}"
            )
        return cleaned or None

    @field_validator("path")
    @classmethod
    def normalize_path(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = str(value).strip()
        if not cleaned:
            return None
        from airpods import state

        path = Path(cleaned).expanduser()
        if not path.is_absolute():
            path = (state.state_root() / path).resolve()
        return str(path)

    @field_validator("ref")
    @classmethod
    def normalize_ref(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("requirements")
    @classmethod
    def normalize_requirements(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def validate_source(self) -> "CustomNodeInstall":
        if bool(self.repo) == bool(self.path):
            raise ValueError(
                "custom node must set exactly one of repo or path (services.comfyui.custom_nodes.install)"
            )
        if self.path:
            path = Path(self.path)
            if not path.exists():
                raise ValueError(f"custom node path not found: {path}")
        return self


class CustomNodesConfig(BaseModel):
    install: List[CustomNodeInstall] = Field(default_factory=list)


class ServiceConfig(BaseModel):
    enabled: bool = True
    image: str
    pod: str
    container: str
    ports: List[PortMapping] = Field(default_factory=list)
    volumes: Dict[str, VolumeMount] = Field(default_factory=dict)
    gpu: GPUConfig = Field(default_factory=GPUConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    env: Dict[str, str] = Field(default_factory=dict)
    resources: ResourceLimits = Field(default_factory=ResourceLimits)
    pids_limit: int = Field(default=2048, ge=1, le=1000000)
    needs_webui_secret: bool = False
    cuda_override: Optional[str] = None
    auto_pull_models: List[str] = Field(default_factory=list)
    auto_configure_ollama: bool = False
    command_args: Dict[str, CommandArgValue] = Field(default_factory=dict)
    entrypoint_override: Optional[List[str]] = None
    default_model: Optional[str] = None
    default_model_url: Optional[str] = None
    custom_nodes: Optional[CustomNodesConfig] = None

    model_config = ConfigDict(extra="ignore")

    @field_validator("image")
    @classmethod
    def validate_image(cls, value: str) -> str:
        if not value or value.isspace():
            raise ValueError("Image cannot be empty")
        if "/" not in value:
            raise ValueError(
                "Image must include registry/repository (e.g. docker.io/library/image)"
            )
        return value

    @field_validator("ports", mode="before")
    @classmethod
    def normalize_ports(cls, value):
        if value is None:
            return []
        if isinstance(value, dict):
            return [value]
        return value

    @field_validator("entrypoint_override")
    @classmethod
    def normalize_entrypoint_override(cls, value):
        if value is None:
            return None
        if isinstance(value, list):
            cleaned = [str(item).strip() for item in value if str(item).strip()]
            return cleaned or None
        return None


class AirpodsConfig(BaseModel):
    meta: MetaConfig = Field(default_factory=MetaConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    cli: CLIConfig = Field(default_factory=CLIConfig)
    dependencies: DependenciesConfig = Field(default_factory=DependenciesConfig)
    services: Dict[str, ServiceConfig] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="after")
    def ensure_required_services(self) -> "AirpodsConfig":
        required = {"ollama", "open-webui"}
        missing = sorted(name for name in required if name not in self.services)
        if missing:
            raise ValueError(
                f"Missing required service definitions: {', '.join(missing)}"
            )
        return self

    @model_validator(mode="after")
    def ensure_llamacpp_model(self) -> "AirpodsConfig":
        service = self.services.get("llamacpp")
        if not service or not service.enabled:
            return self
        model_arg = service.command_args.get("model") if service.command_args else None
        if model_arg is not None and not isinstance(model_arg, str):
            raise ValueError("llamacpp command_args.model must be a string")
        if isinstance(model_arg, str):
            model_arg = model_arg.strip() or None
        if not model_arg and not service.default_model:
            raise ValueError(
                "llamacpp requires command_args.model or default_model to be set"
            )
        return self

    @classmethod
    def from_dict(cls, data: dict) -> "AirpodsConfig":
        return cls.model_validate(data)

    def to_dict(self) -> dict:
        return self.model_dump(by_alias=True, exclude_none=True)
