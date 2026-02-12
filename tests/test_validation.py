"""Tests for record-level validation."""

import pytest

from neo4j_ingest.validation import (
    ErrorStrategy,
    RecordValidator,
    ValidationRule,
)


def _make_records():
    return [
        {"id": 1, "name": "Alice", "email": "alice@example.com", "age": "30"},
        {"id": 2, "name": "", "email": "bad-email", "age": "25"},
        {"id": None, "name": "Charlie", "email": "c@example.com", "age": "200"},
    ]


class TestValidationRule:
    def test_required_pass(self):
        rule = ValidationRule(field="name", rule="required")
        assert rule.check({"name": "Alice"}) is None

    def test_required_fail_none(self):
        rule = ValidationRule(field="name", rule="required")
        assert rule.check({"name": None}) is not None

    def test_required_fail_empty(self):
        rule = ValidationRule(field="name", rule="required")
        assert rule.check({"name": ""}) is not None

    def test_regex_pass(self):
        rule = ValidationRule(field="email", rule="regex", params={"pattern": r"^[^@]+@[^@]+\.[^@]+$"})
        assert rule.check({"email": "a@b.com"}) is None

    def test_regex_fail(self):
        rule = ValidationRule(field="email", rule="regex", params={"pattern": r"^[^@]+@[^@]+\.[^@]+$"})
        assert rule.check({"email": "bad-email"}) is not None

    def test_min_pass(self):
        rule = ValidationRule(field="age", rule="min", params={"value": 0})
        assert rule.check({"age": 25}) is None

    def test_min_fail(self):
        rule = ValidationRule(field="age", rule="min", params={"value": 0})
        assert rule.check({"age": -1}) is not None

    def test_max_pass(self):
        rule = ValidationRule(field="age", rule="max", params={"value": 150})
        assert rule.check({"age": 100}) is None

    def test_max_fail(self):
        rule = ValidationRule(field="age", rule="max", params={"value": 150})
        assert rule.check({"age": 200}) is not None

    def test_one_of_pass(self):
        rule = ValidationRule(field="status", rule="one_of", params={"values": ["active", "inactive"]})
        assert rule.check({"status": "active"}) is None

    def test_one_of_fail(self):
        rule = ValidationRule(field="status", rule="one_of", params={"values": ["active", "inactive"]})
        assert rule.check({"status": "deleted"}) is not None

    def test_custom_message(self):
        rule = ValidationRule(field="name", rule="required", message="Name is mandatory")
        err = rule.check({"name": ""})
        assert err == "Name is mandatory"


class TestRecordValidator:
    def test_skip_strategy(self):
        validator = RecordValidator(
            rules=[ValidationRule(field="id", rule="required")],
            strategy=ErrorStrategy.SKIP,
        )
        records = _make_records()
        result = validator.validate(records)
        assert len(result.valid_records) == 2
        assert result.total_errors == 1

    def test_fail_strategy(self):
        validator = RecordValidator(
            rules=[ValidationRule(field="id", rule="required")],
            strategy=ErrorStrategy.FAIL,
        )
        with pytest.raises(ValueError, match="Validation failed"):
            validator.validate(_make_records())

    def test_dead_letter_strategy(self):
        validator = RecordValidator(
            rules=[ValidationRule(field="id", rule="required")],
            strategy=ErrorStrategy.DEAD_LETTER,
        )
        result = validator.validate(_make_records())
        assert len(result.valid_records) == 2
        assert result.total_errors == 1
        assert result.errors[0].record["name"] == "Charlie"

    def test_no_rules_passes_all(self):
        validator = RecordValidator(rules=[], strategy=ErrorStrategy.SKIP)
        records = [{"a": 1}, {"a": 2}]
        result = validator.validate(records)
        assert len(result.valid_records) == 2
        assert result.total_errors == 0
