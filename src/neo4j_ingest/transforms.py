"""Data transformation pipeline.

Transforms are applied per-field during ingestion, allowing type casting,
string manipulation, computed fields, and custom logic — all driven by config.

Config example:
    properties:
      - source_field: price
        target: price
        transform:
          type: to_float
      - source_field: name
        target: name_upper
        transform:
          type: uppercase
      - source_field: created_at
        target: created_at
        transform:
          type: to_datetime
          params:
            format: "%Y-%m-%d"
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from neo4j_ingest.registry import transform_registry

logger = logging.getLogger(__name__)


# Built-in transforms --------------------------------------------------------

@transform_registry.register("to_string")
def to_string(value: Any, **kwargs: Any) -> str | None:
    if value is None:
        return None
    return str(value)


@transform_registry.register("to_int")
def to_int(value: Any, **kwargs: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


@transform_registry.register("to_float")
def to_float(value: Any, **kwargs: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


@transform_registry.register("to_bool")
def to_bool(value: Any, **kwargs: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("true", "1", "yes", "y")


@transform_registry.register("to_datetime")
def to_datetime(value: Any, *, format: str = "%Y-%m-%dT%H:%M:%S", **kwargs: Any) -> str | None:
    """Parse a datetime string and re-format it as ISO 8601 for Neo4j."""
    if value is None or value == "":
        return None
    dt = datetime.strptime(str(value), format)
    return dt.isoformat()


@transform_registry.register("uppercase")
def uppercase(value: Any, **kwargs: Any) -> str | None:
    if value is None:
        return None
    return str(value).upper()


@transform_registry.register("lowercase")
def lowercase(value: Any, **kwargs: Any) -> str | None:
    if value is None:
        return None
    return str(value).lower()


@transform_registry.register("strip")
def strip(value: Any, **kwargs: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip()


@transform_registry.register("replace")
def replace_transform(value: Any, *, old: str = "", new: str = "", **kwargs: Any) -> str | None:
    if value is None:
        return None
    return str(value).replace(old, new)


@transform_registry.register("default")
def default_value(value: Any, *, default: Any = None, **kwargs: Any) -> Any:
    """Return *default* when value is None or empty string."""
    if value is None or value == "":
        return default
    return value


@transform_registry.register("template")
def template_transform(value: Any, *, template: str = "{value}", **kwargs: Any) -> str | None:
    """Format a string template. The original value is available as {value}."""
    if value is None:
        return None
    return template.format(value=value)


# Pipeline runner ------------------------------------------------------------

def apply_transform(value: Any, transform_cfg: dict) -> Any:
    """Apply a single transform config to a value.

    transform_cfg is expected to have:
        {"type": "to_float"}
    or:
        {"type": "to_datetime", "params": {"format": "%Y-%m-%d"}}
    """
    transform_type = transform_cfg["type"]
    params = transform_cfg.get("params", {})

    fn = transform_registry.get(transform_type)
    if fn is None:
        raise ValueError(
            f"Unknown transform type '{transform_type}'. "
            f"Available: {transform_registry.keys()}"
        )
    return fn(value, **params)


def apply_transforms(value: Any, transforms: list[dict] | dict | None) -> Any:
    """Apply one or more transforms in sequence."""
    if transforms is None:
        return value
    if isinstance(transforms, dict):
        transforms = [transforms]
    for t in transforms:
        value = apply_transform(value, t)
    return value
