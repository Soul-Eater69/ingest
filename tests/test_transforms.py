"""Tests for the data transformation pipeline."""

import pytest

from neo4j_ingest.transforms import (
    apply_transform,
    apply_transforms,
    to_int,
    to_float,
    to_bool,
    to_string,
    to_datetime,
    uppercase,
    lowercase,
    strip,
    replace_transform,
    default_value,
    template_transform,
)


class TestBuiltinTransforms:
    def test_to_string(self):
        assert to_string(42) == "42"
        assert to_string(None) is None

    def test_to_int(self):
        assert to_int("42") == 42
        assert to_int(None) is None
        assert to_int("") is None

    def test_to_float(self):
        assert to_float("3.14") == 3.14
        assert to_float(None) is None

    def test_to_bool_true(self):
        assert to_bool("true") is True
        assert to_bool("1") is True
        assert to_bool("yes") is True
        assert to_bool(True) is True

    def test_to_bool_false(self):
        assert to_bool("false") is False
        assert to_bool("0") is False
        assert to_bool("no") is False
        assert to_bool(None) is None

    def test_to_datetime(self):
        result = to_datetime("2023-01-15", format="%Y-%m-%d")
        assert result == "2023-01-15T00:00:00"
        assert to_datetime(None) is None
        assert to_datetime("") is None

    def test_uppercase(self):
        assert uppercase("hello") == "HELLO"
        assert uppercase(None) is None

    def test_lowercase(self):
        assert lowercase("HELLO") == "hello"
        assert lowercase(None) is None

    def test_strip(self):
        assert strip("  hello  ") == "hello"
        assert strip(None) is None

    def test_replace(self):
        assert replace_transform("foo-bar", old="-", new="_") == "foo_bar"
        assert replace_transform(None) is None

    def test_default_value(self):
        assert default_value(None, default="N/A") == "N/A"
        assert default_value("", default="N/A") == "N/A"
        assert default_value("real", default="N/A") == "real"

    def test_template(self):
        assert template_transform("Alice", template="Hello, {value}!") == "Hello, Alice!"
        assert template_transform(None) is None


class TestApplyTransform:
    def test_single_transform(self):
        result = apply_transform("42", {"type": "to_int"})
        assert result == 42

    def test_transform_with_params(self):
        result = apply_transform("2023-01-01", {"type": "to_datetime", "params": {"format": "%Y-%m-%d"}})
        assert result == "2023-01-01T00:00:00"

    def test_unknown_transform_raises(self):
        with pytest.raises(ValueError, match="Unknown transform"):
            apply_transform("x", {"type": "nonexistent"})


class TestApplyTransforms:
    def test_none_returns_value(self):
        assert apply_transforms("hello", None) == "hello"

    def test_single_dict(self):
        assert apply_transforms("  HELLO  ", {"type": "strip"}) == "HELLO"

    def test_chain(self):
        transforms = [
            {"type": "strip"},
            {"type": "lowercase"},
        ]
        assert apply_transforms("  HELLO  ", transforms) == "hello"
