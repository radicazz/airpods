"""Pydantic models describing the configuration schema."""

from __future__ import annotations

from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MetaConfig(BaseModel):
    version: str = "1.0"


class RuntimeConfig(BaseModel):
    prefer: Literal["auto", "podman", "docker"] = "auto"
    host_gateway: str = "auto"
    network_name: str = "airpods_network"
    gpu_device_flag: str = "auto"
    restart_policy: Literal["no", "on-failure", "always", "unless-stopped"] = (
        "unless-stopped"
    )


class CLIConfig(BaseModel):
    stop_timeout: int = Field(default=10, ge=1, le=300)
    log_lines: int = Field(default=200, ge=1, le=10000)
    ping_timeout: float = Field(default=2.0, ge=0.1, le=60.0)
    startup_timeout: int = Field(default=120, ge=10, le=600)
    startup_check_interval: float = Field(default=2.0, ge=0.5, le=10.0)
    auto_confirm: bool = False
    debug: bool = False


class DependenciesConfig(BaseModel):
    required: List[str] = Field(
        default_factory=lambda: ["podman", "podman-compose", "uv"]
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
    needs_webui_secret: bool = False

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

    @classmethod
    def from_dict(cls, data: dict) -> "AirpodsConfig":
        return cls.model_validate(data)

    def to_dict(self) -> dict:
        return self.model_dump(by_alias=True, exclude_none=True)
