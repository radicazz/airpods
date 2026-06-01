"""Configuration loading, merging, and caching."""

from __future__ import annotations

import copy
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover
    import tomli as tomllib

from airpods import state
from airpods.paths import detect_repo_root

from .defaults import DEFAULT_CONFIG_DICT
from .errors import ConfigurationError
from .resolver import resolve_templates
from .schema import AirpodsConfig


def _config_home(path: Path) -> Path:
    parent = path.parent
    if parent.name == "configs":
        return parent.parent
    return parent


def _resolve_and_register(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    state.set_state_root(_config_home(resolved))
    return resolved


@lru_cache(maxsize=1)
def locate_config_file() -> Optional[Path]:
    """Locate the configuration file using the documented priority order."""
    env_override = os.environ.get("AIRPODS_CONFIG")
    if env_override:
        path = Path(env_override).expanduser()
        if not path.exists():
            raise ConfigurationError(f"AIRPODS_CONFIG points to missing file: {path}")
        return _resolve_and_register(path)

    airpods_home_env = os.environ.get("AIRPODS_HOME")
    if airpods_home_env:
        base = Path(airpods_home_env).expanduser()
        state.set_state_root(base)
        for candidate in (base / "configs" / "config.toml", base / "config.toml"):
            if candidate.exists():
                return _resolve_and_register(candidate)
        return None

    repo_root = detect_repo_root()
    if repo_root:
        for candidate in (
            repo_root / "configs" / "config.toml",
            repo_root / "config.toml",
        ):
            if candidate.exists():
                return _resolve_and_register(candidate)

    xdg_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_home:
        base = Path(xdg_home).expanduser() / "airpods"
        for candidate in (base / "configs" / "config.toml", base / "config.toml"):
            if candidate.exists():
                return _resolve_and_register(candidate)

    home_base = Path.home() / ".config" / "airpods"
    for candidate in (home_base / "configs" / "config.toml", home_base / "config.toml"):
        if candidate.exists():
            return _resolve_and_register(candidate)

    return None


def load_toml(path: Path) -> Dict[str, Any]:
    """Load a TOML file with helpful error reporting."""
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"Invalid TOML in {path}: {exc}") from exc
    except OSError as exc:  # pragma: no cover - file permission/path errors
        raise ConfigurationError(f"Cannot read config file {path}: {exc}") from exc


def merge_configs(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge dictionaries, returning a new dict."""
    result: Dict[str, Any] = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_config() -> AirpodsConfig:
    """Load, validate and resolve the effective configuration."""
    config_data = copy.deepcopy(DEFAULT_CONFIG_DICT)
    if config_path := locate_config_file():
        user_config = load_toml(config_path)
        config_data = merge_configs(config_data, user_config)
    # Normalize legacy llama.cpp registry if present in user config.
    services = config_data.get("services", {})
    llamacpp = services.get("llamacpp")
    if isinstance(llamacpp, dict):
        image = llamacpp.get("image")
        if isinstance(image, str) and image.startswith("ghcr.io/ggerganov/llama.cpp"):
            llamacpp["image"] = image.replace(
                "ghcr.io/ggerganov/llama.cpp", "ghcr.io/ggml-org/llama.cpp", 1
            )
        command_args = llamacpp.get("command_args")
        ports = llamacpp.get("ports")
        if isinstance(command_args, dict) and isinstance(ports, list) and ports:
            try:
                host_port = ports[0].get("host")
                container_port = ports[0].get("container")
            except (AttributeError, IndexError, TypeError):
                host_port = None
                container_port = None
            port_arg = command_args.get("port")
            if (
                isinstance(host_port, int)
                and isinstance(container_port, int)
                and host_port != container_port
                and (port_arg is None or port_arg == container_port)
            ):
                command_args["port"] = host_port
    try:
        config = AirpodsConfig.from_dict(config_data)
    except ValueError as exc:
        raise ConfigurationError(f"Invalid configuration: {exc}") from exc
    config = _apply_runtime_defaults(config)
    config = resolve_templates(config)
    return config


_CONFIG_INSTANCE: Optional[AirpodsConfig] = None


def get_config() -> AirpodsConfig:
    """Get the cached configuration object."""
    global _CONFIG_INSTANCE
    if _CONFIG_INSTANCE is None:
        _CONFIG_INSTANCE = load_config()
    return _CONFIG_INSTANCE


def reload_config() -> AirpodsConfig:
    """Force reload configuration from disk."""
    global _CONFIG_INSTANCE
    locate_config_file.cache_clear()
    _CONFIG_INSTANCE = load_config()
    return _CONFIG_INSTANCE


def _apply_runtime_defaults(config: AirpodsConfig) -> AirpodsConfig:
    return config
