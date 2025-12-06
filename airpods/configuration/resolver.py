"""Template resolution for configuration values."""

from __future__ import annotations

import re
from typing import Any, Dict, Set

from .errors import ConfigurationError
from .schema import AirpodsConfig

TEMPLATE_PATTERN = re.compile(r"\{\{([^}]+)\}\}")
MAX_RESOLUTION_DEPTH = 100


def resolve_caddyfile_template(template: str, config: AirpodsConfig) -> str:
    """Resolve template variables in Caddyfile template.
    
    This is a simpler resolver that only processes {{variable}} patterns
    once, without recursion. This avoids conflicts with Caddy's own { } syntax.
    
    Args:
        template: Caddyfile template content
        config: Loaded configuration
        
    Returns:
        Resolved Caddyfile content
    """
    data = config.to_dict()
    
    # Build context
    context = {
        "runtime": data.get("runtime", {}),
        "services": {},
    }
    for service_name, service_data in data.get("services", {}).items():
        ports = service_data.get("ports", [])
        context["services"][service_name] = {
            "ports": ports,
            "image": service_data.get("image"),
            "pod": service_data.get("pod"),
        }
    
    # Single-pass replacement (no recursion)
    missing: list[str] = []
    
    def _replace(match: re.Match[str]) -> str:
        path = match.group(1).strip()
        value = _lookup_path(path, context)
        if value is None:
            missing.append(path)
            return match.group(0)
        return str(value)
    
    resolved = TEMPLATE_PATTERN.sub(_replace, template)
    
    if missing:
        refs = ", ".join(sorted(set(missing)))
        raise ConfigurationError(
            f"Template variables not found in Caddyfile: {refs}"
        )
    
    return resolved


def resolve_templates(config: AirpodsConfig) -> AirpodsConfig:
    """Resolve supported template variables inside configuration env vars."""
    data = config.to_dict()

    context = {
        "runtime": data.get("runtime", {}),
        "services": {},
    }
    for service_name, service_data in data.get("services", {}).items():
        ports = service_data.get("ports", [])
        ports_list = []
        if isinstance(ports, dict):
            ports_list = [ports]
        elif isinstance(ports, list):
            ports_list = ports
        context["services"][service_name] = {
            "ports": ports_list,
            "image": service_data.get("image"),
            "pod": service_data.get("pod"),
        }

    services = data.get("services", {})
    for service_name, service_data in services.items():
        env = service_data.get("env", {})
        for key, value in list(env.items()):
            if isinstance(value, str) and "{{" in value:
                env[key] = _resolve_string(
                    value, context, location=f"services.{service_name}.env.{key}"
                )

    return AirpodsConfig.from_dict(data)


def _resolve_string(template: str, context: Dict[str, Any], *, location: str) -> str:
    missing: list[str] = []
    seen_refs: Set[str] = set()
    iteration = 0

    current = template
    while "{{" in current:
        if iteration >= MAX_RESOLUTION_DEPTH:
            raise ConfigurationError(
                f"Circular reference or excessive nesting detected in {location}"
            )
        iteration += 1

        def _replace(match: re.Match[str]) -> str:
            path = match.group(1).strip()
            if path in seen_refs:
                raise ConfigurationError(
                    f"Circular reference detected: {{{{path}}}} in {location}"
                )
            seen_refs.add(path)
            value = _lookup_path(path, context)
            if value is None:
                missing.append(path)
                return match.group(0)
            return str(value)

        resolved = TEMPLATE_PATTERN.sub(_replace, current)
        if resolved == current:
            break
        current = resolved

    if missing:
        refs = ", ".join(sorted(set(missing)))
        raise ConfigurationError(
            f"Unknown template reference(s) [{refs}] in {location}"
        )
    return current


def _lookup_path(path: str, context: Dict[str, Any]) -> Any:
    keys = path.split(".")
    value: Any = context
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
        elif isinstance(value, list):
            try:
                index = int(key)
                value = value[index] if 0 <= index < len(value) else None
            except (ValueError, IndexError):
                return None
        else:
            return None
    return value
