"""Record-level validation with configurable error handling strategies.

Enterprise systems can't afford to silently drop data or crash on a single
bad record. This module provides:
- Field-level validation rules (required, type checks, regex, ranges)
- Error strategies: SKIP (log and continue), FAIL (abort), DEAD_LETTER (collect)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ErrorStrategy(str, Enum):
    SKIP = "skip"
    FAIL = "fail"
    DEAD_LETTER = "dead_letter"


@dataclass
class ValidationRule:
    """A single validation rule for a field."""

    field: str
    rule: str  # "required", "type", "regex", "min", "max", "one_of"
    params: dict[str, Any] = field(default_factory=dict)
    message: str | None = None

    def check(self, record: dict[str, Any]) -> str | None:
        """Return an error message if the rule fails, else None."""
        value = record.get(self.field)

        if self.rule == "required":
            if value is None or value == "":
                return self.message or f"Field '{self.field}' is required"

        elif self.rule == "type":
            expected = self.params.get("expected", "str")
            type_map = {"str": str, "int": int, "float": float, "bool": bool}
            expected_type = type_map.get(expected)
            if expected_type and value is not None and not isinstance(value, expected_type):
                # Try conversion
                try:
                    expected_type(value)
                except (ValueError, TypeError):
                    return (
                        self.message
                        or f"Field '{self.field}' expected type {expected}, got {type(value).__name__}"
                    )

        elif self.rule == "regex":
            pattern = self.params.get("pattern", "")
            if value is not None and not re.match(pattern, str(value)):
                return (
                    self.message
                    or f"Field '{self.field}' does not match pattern '{pattern}'"
                )

        elif self.rule == "min":
            min_val = self.params.get("value")
            if value is not None and min_val is not None:
                try:
                    if float(value) < float(min_val):
                        return self.message or f"Field '{self.field}' below minimum {min_val}"
                except (ValueError, TypeError):
                    pass

        elif self.rule == "max":
            max_val = self.params.get("value")
            if value is not None and max_val is not None:
                try:
                    if float(value) > float(max_val):
                        return self.message or f"Field '{self.field}' above maximum {max_val}"
                except (ValueError, TypeError):
                    pass

        elif self.rule == "one_of":
            allowed = self.params.get("values", [])
            if value is not None and value not in allowed:
                return (
                    self.message
                    or f"Field '{self.field}' must be one of {allowed}, got '{value}'"
                )

        return None


@dataclass
class ValidationError:
    """A failed validation on a specific record."""

    record_index: int
    record: dict[str, Any]
    errors: list[str]


@dataclass
class ValidationResult:
    """Result of validating a batch of records."""

    valid_records: list[dict[str, Any]] = field(default_factory=list)
    errors: list[ValidationError] = field(default_factory=list)

    @property
    def total_errors(self) -> int:
        return len(self.errors)


class RecordValidator:
    """Validates records according to rules and an error strategy."""

    def __init__(
        self,
        rules: list[ValidationRule],
        strategy: ErrorStrategy = ErrorStrategy.SKIP,
    ) -> None:
        self.rules = rules
        self.strategy = strategy

    def validate(self, records: list[dict[str, Any]]) -> ValidationResult:
        result = ValidationResult()

        for idx, record in enumerate(records):
            errors = []
            for rule in self.rules:
                err = rule.check(record)
                if err:
                    errors.append(err)

            if errors:
                ve = ValidationError(record_index=idx, record=record, errors=errors)

                if self.strategy == ErrorStrategy.FAIL:
                    raise ValueError(
                        f"Validation failed at record {idx}: {'; '.join(errors)}"
                    )
                elif self.strategy == ErrorStrategy.SKIP:
                    logger.warning(
                        "Skipping record %d: %s", idx, "; ".join(errors)
                    )
                    result.errors.append(ve)
                elif self.strategy == ErrorStrategy.DEAD_LETTER:
                    result.errors.append(ve)
            else:
                result.valid_records.append(record)

        if result.errors:
            logger.info(
                "Validation: %d passed, %d failed (%s strategy)",
                len(result.valid_records),
                len(result.errors),
                self.strategy.value,
            )
        return result
