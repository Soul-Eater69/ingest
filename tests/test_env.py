"""Tests for environment variable substitution."""

import os

import pytest

from neo4j_ingest.env import MissingEnvironmentVariable, resolve_env_vars, _substitute_string


class TestSubstituteString:
    def test_no_vars(self):
        assert _substitute_string("hello world") == "hello world"

    def test_simple_var(self, monkeypatch):
        monkeypatch.setenv("MY_VAR", "value123")
        assert _substitute_string("${MY_VAR}") == "value123"

    def test_var_with_surrounding_text(self, monkeypatch):
        monkeypatch.setenv("HOST", "db.example.com")
        assert _substitute_string("bolt://${HOST}:7687") == "bolt://db.example.com:7687"

    def test_var_with_default(self, monkeypatch):
        monkeypatch.delenv("MISSING_VAR", raising=False)
        assert _substitute_string("${MISSING_VAR:-fallback}") == "fallback"

    def test_var_with_default_but_set(self, monkeypatch):
        monkeypatch.setenv("SET_VAR", "real_value")
        assert _substitute_string("${SET_VAR:-fallback}") == "real_value"

    def test_missing_required_var_raises(self, monkeypatch):
        monkeypatch.delenv("REQUIRED_VAR", raising=False)
        with pytest.raises(MissingEnvironmentVariable, match="REQUIRED_VAR"):
            _substitute_string("${REQUIRED_VAR}")

    def test_multiple_vars(self, monkeypatch):
        monkeypatch.setenv("USER", "admin")
        monkeypatch.setenv("PASS", "secret")
        result = _substitute_string("${USER}:${PASS}")
        assert result == "admin:secret"

    def test_empty_default(self, monkeypatch):
        monkeypatch.delenv("EMPTY_DEFAULT", raising=False)
        assert _substitute_string("${EMPTY_DEFAULT:-}") == ""


class TestResolveEnvVars:
    def test_nested_dict(self, monkeypatch):
        monkeypatch.setenv("DB_HOST", "neo4j.prod")
        data = {"neo4j": {"uri": "bolt://${DB_HOST}:7687"}, "name": "test"}
        result = resolve_env_vars(data)
        assert result["neo4j"]["uri"] == "bolt://neo4j.prod:7687"
        assert result["name"] == "test"

    def test_list(self, monkeypatch):
        monkeypatch.setenv("VAL", "x")
        data = ["${VAL}", "plain", "${VAL}"]
        assert resolve_env_vars(data) == ["x", "plain", "x"]

    def test_non_string_passthrough(self):
        assert resolve_env_vars(42) == 42
        assert resolve_env_vars(True) is True
        assert resolve_env_vars(None) is None
