"""Tests for deterministic ID generation."""

import hashlib

import pytest

from neo4j_ingest.id_generation import IdGenerationConfig


class TestSha256Strategy:
    def test_basic_hash(self):
        cfg = IdGenerationConfig(
            strategy="sha256-hash",
            fields=["name"],
            hash_length=16,
        )
        record = {"name": "Alice"}
        result = cfg.generate_id(record)

        # Verify it matches manual SHA-256
        expected = hashlib.sha256("Alice".encode()).hexdigest()[:16]
        assert result == expected

    def test_deterministic(self):
        """Same input → same ID every time."""
        cfg = IdGenerationConfig(
            strategy="sha256-hash",
            fields=["repo", "class"],
            hash_length=16,
        )
        record = {"repo": "my-repo", "class": "MyClass"}
        id1 = cfg.generate_id(record)
        id2 = cfg.generate_id(record)
        assert id1 == id2

    def test_different_inputs_different_ids(self):
        cfg = IdGenerationConfig(
            strategy="sha256-hash",
            fields=["name"],
            hash_length=16,
        )
        id1 = cfg.generate_id({"name": "Alice"})
        id2 = cfg.generate_id({"name": "Bob"})
        assert id1 != id2

    def test_multi_field_hash(self):
        cfg = IdGenerationConfig(
            strategy="sha256-hash",
            fields=["repo", "pkg", "class"],
            hash_length=16,
            separator=":",
        )
        record = {"repo": "r", "pkg": "p", "class": "C"}
        result = cfg.generate_id(record)

        expected = hashlib.sha256("r:p:C".encode()).hexdigest()[:16]
        assert result == expected

    def test_custom_hash_length(self):
        cfg = IdGenerationConfig(
            strategy="sha256-hash",
            fields=["name"],
            hash_length=8,
        )
        result = cfg.generate_id({"name": "test"})
        assert len(result) == 8

    def test_prefix(self):
        cfg = IdGenerationConfig(
            strategy="sha256-hash",
            fields=["name"],
            hash_length=8,
            prefix="method_",
        )
        result = cfg.generate_id({"name": "test"})
        assert result.startswith("method_")
        # prefix + 8 hex chars
        assert len(result) == 8 + len("method_")

    def test_none_field_treated_as_empty_string(self):
        cfg = IdGenerationConfig(
            strategy="sha256-hash",
            fields=["name", "missing"],
            hash_length=16,
        )
        record = {"name": "Alice"}
        result = cfg.generate_id(record)
        # Should not raise, missing field → ""
        assert len(result) == 16


class TestCompositeStrategy:
    def test_basic_composite(self):
        cfg = IdGenerationConfig(
            strategy="composite",
            fields=["repo", "class"],
            separator=":",
        )
        result = cfg.generate_id({"repo": "my-repo", "class": "MyClass"})
        assert result == "my-repo:MyClass"

    def test_custom_separator(self):
        cfg = IdGenerationConfig(
            strategy="composite",
            fields=["a", "b"],
            separator="/",
        )
        assert cfg.generate_id({"a": "x", "b": "y"}) == "x/y"

    def test_prefix(self):
        cfg = IdGenerationConfig(
            strategy="composite",
            fields=["name"],
            prefix="node_",
        )
        assert cfg.generate_id({"name": "test"}) == "node_test"


class TestPassthroughStrategy:
    def test_passthrough(self):
        cfg = IdGenerationConfig(
            strategy="passthrough",
            fields=["id"],
        )
        assert cfg.generate_id({"id": "abc-123"}) == "abc-123"

    def test_passthrough_with_prefix(self):
        cfg = IdGenerationConfig(
            strategy="passthrough",
            fields=["id"],
            prefix="node_",
        )
        assert cfg.generate_id({"id": "123"}) == "node_123"

    def test_passthrough_no_fields_raises(self):
        cfg = IdGenerationConfig(strategy="passthrough", fields=[])
        with pytest.raises(ValueError, match="at least one field"):
            cfg.generate_id({"id": "x"})

    def test_passthrough_none_value_raises(self):
        cfg = IdGenerationConfig(strategy="passthrough", fields=["id"])
        with pytest.raises(ValueError, match="is None"):
            cfg.generate_id({"other": "x"})
