"""Tests for data source connectors."""

import json

import pytest

from neo4j_ingest.config import SourceConfig
from neo4j_ingest.sources import read_csv, read_json, read_source, _resolve_json_root


class TestResolvJsonRoot:
    def test_list_without_root(self):
        data = [{"a": 1}, {"a": 2}]
        assert _resolve_json_root(data, None) == data

    def test_nested_path(self):
        data = {"response": {"items": [{"x": 1}]}}
        assert _resolve_json_root(data, "response.items") == [{"x": 1}]

    def test_non_list_raises(self):
        with pytest.raises(ValueError, match="not a list"):
            _resolve_json_root({"a": 1}, None)

    def test_bad_path_raises(self):
        with pytest.raises((ValueError, KeyError)):
            _resolve_json_root({"a": 1}, "b.c")


class TestReadCsv:
    def test_read_csv(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("id,name\n1,Alice\n2,Bob\n")
        cfg = SourceConfig(name="test", type="csv", path=str(csv_file))
        records = read_csv(cfg)
        assert len(records) == 2
        assert records[0]["name"] == "Alice"


class TestReadJson:
    def test_read_flat_list(self, tmp_path):
        json_file = tmp_path / "test.json"
        json_file.write_text(json.dumps([{"id": 1}, {"id": 2}]))
        cfg = SourceConfig(name="test", type="json", path=str(json_file))
        records = read_json(cfg)
        assert len(records) == 2

    def test_read_nested(self, tmp_path):
        json_file = tmp_path / "test.json"
        json_file.write_text(json.dumps({"data": {"rows": [{"id": 1}]}}))
        cfg = SourceConfig(
            name="test", type="json", path=str(json_file), json_root="data.rows"
        )
        records = read_json(cfg)
        assert len(records) == 1


class TestReadSource:
    def test_dispatch_csv(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("id,val\n1,a\n")
        cfg = SourceConfig(name="test", type="csv", path=str(csv_file))
        records = read_source(cfg)
        assert len(records) == 1

    def test_unknown_type_raises(self):
        # Force an unsupported type past validation
        cfg = SourceConfig.model_construct(name="x", type="ftp")
        with pytest.raises(ValueError, match="Unsupported"):
            read_source(cfg)
