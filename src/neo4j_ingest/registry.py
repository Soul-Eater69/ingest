"""Plugin registry for extensible source readers and transformers.

Enterprise systems need extensibility without modifying core code.
This module provides a decorator-based registry so teams can add
custom source types and transform functions.

Usage:

    from neo4j_ingest.registry import source_registry, transform_registry

    @source_registry.register("kafka")
    def read_kafka(config: SourceConfig) -> list[dict]:
        ...

    @transform_registry.register("uppercase")
    def uppercase(value, **kwargs):
        return str(value).upper()
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class Registry:
    """A named registry mapping string keys to callables."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._entries: dict[str, Callable] = {}

    def register(self, key: str) -> Callable:
        """Decorator to register a callable under *key*."""

        def decorator(fn: Callable) -> Callable:
            if key in self._entries:
                logger.warning(
                    "%s registry: overwriting existing entry '%s'", self.name, key
                )
            self._entries[key] = fn
            logger.debug("%s registry: registered '%s'", self.name, key)
            return fn

        return decorator

    def get(self, key: str) -> Callable | None:
        return self._entries.get(key)

    def __contains__(self, key: str) -> bool:
        return key in self._entries

    def keys(self) -> list[str]:
        return list(self._entries.keys())


# Global registries ----------------------------------------------------------

source_registry = Registry("source")
transform_registry = Registry("transform")
