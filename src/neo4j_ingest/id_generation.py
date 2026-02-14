"""Deterministic ID generation strategies for knowledge graph nodes.

Supports multiple strategies for generating node IDs from source data:
- **sha256-hash**: SHA-256 hash of natural key fields (deterministic, collision-free)
- **composite**: Concatenation of key fields with a separator
- **passthrough**: Use an existing source field directly

The SHA-256 strategy is particularly useful for knowledge graph mappings where
nodes from different sources or repositories must be consistently identifiable.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class IdGenerationConfig(BaseModel):
    """Configuration for deterministic ID generation.

    Example (YAML):
        id_generation:
          strategy: sha256-hash
          fields: [repo_name, class_name, method_name]
          hash_length: 16
          prefix: "method_"

    Example (JSON KG mapping schema):
        "idGeneration": {
            "strategy": "sha256-hash",
            "hashAlgorithm": "sha256",
            "hashLength": 16
        }
    """

    strategy: Literal["sha256-hash", "composite", "passthrough"] = "sha256-hash"
    fields: list[str] = Field(default_factory=list)
    hash_length: int = 16
    separator: str = ":"
    prefix: str = ""

    def generate_id(self, record: dict[str, Any]) -> str:
        """Generate a deterministic ID from a source record."""
        if self.strategy == "sha256-hash":
            return self._sha256_id(record)
        elif self.strategy == "composite":
            return self._composite_id(record)
        elif self.strategy == "passthrough":
            return self._passthrough_id(record)
        else:
            raise ValueError(f"Unknown ID generation strategy: {self.strategy}")

    def _sha256_id(self, record: dict[str, Any]) -> str:
        """Generate a truncated SHA-256 hash from natural key fields."""
        parts = []
        for field in self.fields:
            val = record.get(field)
            parts.append(str(val) if val is not None else "")
        raw = self.separator.join(parts)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        result = digest[: self.hash_length]
        if self.prefix:
            result = self.prefix + result
        return result

    def _composite_id(self, record: dict[str, Any]) -> str:
        """Generate an ID by concatenating key fields."""
        parts = []
        for field in self.fields:
            val = record.get(field)
            parts.append(str(val) if val is not None else "")
        result = self.separator.join(parts)
        if self.prefix:
            result = self.prefix + result
        return result

    def _passthrough_id(self, record: dict[str, Any]) -> str:
        """Use the first field's value directly as the ID."""
        if not self.fields:
            raise ValueError("passthrough strategy requires at least one field")
        val = record.get(self.fields[0])
        if val is None:
            raise ValueError(
                f"passthrough field '{self.fields[0]}' is None in record"
            )
        result = str(val)
        if self.prefix:
            result = self.prefix + result
        return result
