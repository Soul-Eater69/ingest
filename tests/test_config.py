"""Tests for config loading and validation."""

import json
import textwrap

import pytest
import yaml

from neo4j_ingest.config import IngestConfig, load_config


def _write_yaml(tmp_path, data):
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(data))
    return p


def _minimal_config(**overrides):
    base = {
        "sources": [{"name": "s1", "type": "csv", "path": "data.csv"}],
        "nodes": [
            {
                "source": "s1",
                "label": "Thing",
                "key": "id",
                "properties": [{"source_field": "id"}],
            }
        ],
    }
    base.update(overrides)
    return base


class TestIngestConfig:
    def test_minimal_config_is_valid(self):
        cfg = IngestConfig.model_validate(_minimal_config())
        assert len(cfg.sources) == 1
        assert cfg.sources[0].name == "s1"
        assert cfg.neo4j.uri == "bolt://localhost:7687"

    def test_csv_source_requires_path(self):
        data = _minimal_config()
        data["sources"][0].pop("path")
        with pytest.raises(Exception, match="path"):
            IngestConfig.model_validate(data)

    def test_sql_source_requires_connection_string_and_query(self):
        data = _minimal_config()
        data["sources"] = [{"name": "s1", "type": "sql"}]
        with pytest.raises(Exception, match="connection_string"):
            IngestConfig.model_validate(data)

    def test_rest_source_requires_url(self):
        data = _minimal_config()
        data["sources"] = [{"name": "s1", "type": "rest"}]
        with pytest.raises(Exception, match="url"):
            IngestConfig.model_validate(data)

    def test_node_referencing_unknown_source_fails(self):
        data = _minimal_config()
        data["nodes"][0]["source"] = "nonexistent"
        with pytest.raises(Exception, match="unknown source"):
            IngestConfig.model_validate(data)

    def test_relationship_referencing_unknown_source_fails(self):
        data = _minimal_config()
        data["relationships"] = [
            {
                "source": "nonexistent",
                "rel_type": "REL",
                "from_label": "A",
                "from_key": "id",
                "from_field": "a_id",
                "to_label": "B",
                "to_key": "id",
                "to_field": "b_id",
            }
        ]
        with pytest.raises(Exception, match="unknown source"):
            IngestConfig.model_validate(data)

    def test_custom_neo4j_settings(self):
        data = _minimal_config(
            neo4j={
                "uri": "bolt://db:7687",
                "username": "admin",
                "password": "secret",
                "database": "mydb",
            }
        )
        cfg = IngestConfig.model_validate(data)
        assert cfg.neo4j.uri == "bolt://db:7687"
        assert cfg.neo4j.database == "mydb"


class TestLoadConfig:
    def test_load_yaml(self, tmp_path):
        p = _write_yaml(tmp_path, _minimal_config())
        cfg = load_config(p)
        assert cfg.sources[0].name == "s1"

    def test_load_json(self, tmp_path):
        p = tmp_path / "config.json"
        p.write_text(json.dumps(_minimal_config()))
        cfg = load_config(p)
        assert cfg.sources[0].name == "s1"
