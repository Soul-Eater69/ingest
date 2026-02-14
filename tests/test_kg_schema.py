"""Tests for KG mapping schema loader."""

import json

import pytest

from neo4j_ingest.config import load_config
from neo4j_ingest.kg_schema import (
    is_kg_mapping_schema,
    load_kg_schema,
    load_kg_schema_from_dict,
)


def _minimal_kg_schema(**overrides):
    """Build a minimal KG mapping schema dict."""
    base = {
        "$id": "test-kg-schema.json",
        "title": "Test KG Schema",
        "version": "1.0.0",
        "idGeneration": {
            "strategy": "sha256-hash",
            "hashLength": 16,
        },
        "sourceDefinitions": {
            "src1": {
                "description": "Test source",
                "dataFormat": "JSONL files",
                "examples": ["data/test.jsonl"],
            }
        },
        "nodes": [
            {
                "label": "Person",
                "naturalKey": ["name"],
                "idField": "_id",
                "source": "src1",
                "properties": {
                    "name": {
                        "source": "src1",
                        "sourceField": "full_name",
                        "type": "string",
                        "required": True,
                    },
                    "age": {
                        "source": "src1",
                        "sourceField": "age",
                        "type": "int",
                        "required": False,
                    },
                },
            }
        ],
        "relationships": [],
    }
    base.update(overrides)
    return base


class TestIsKgMappingSchema:
    def test_detects_by_dollar_id(self):
        assert is_kg_mapping_schema({"$id": "test.json"}) is True

    def test_detects_by_id_generation(self):
        assert is_kg_mapping_schema({"idGeneration": {}}) is True

    def test_detects_by_source_definitions(self):
        assert is_kg_mapping_schema({"sourceDefinitions": {}}) is True

    def test_detects_by_node_structure(self):
        data = {
            "nodes": [
                {
                    "label": "Test",
                    "properties": {"name": {"sourceField": "n"}},
                }
            ]
        }
        assert is_kg_mapping_schema(data) is True

    def test_rejects_standard_config(self):
        """Standard IngestConfig nodes have list properties, not dict."""
        data = {
            "nodes": [
                {
                    "source": "s1",
                    "label": "Test",
                    "key": "id",
                    "properties": [{"source_field": "id"}],
                }
            ]
        }
        assert is_kg_mapping_schema(data) is False

    def test_rejects_empty_dict(self):
        assert is_kg_mapping_schema({}) is False


class TestLoadKgSchema:
    def test_basic_node_parsing(self):
        cfg = load_kg_schema_from_dict(_minimal_kg_schema())

        assert len(cfg.nodes) == 1
        node = cfg.nodes[0]
        assert node.label == "Person"
        assert node.key == "_id"
        assert node.source == "src1"

    def test_property_mapping(self):
        cfg = load_kg_schema_from_dict(_minimal_kg_schema())
        node = cfg.nodes[0]

        assert len(node.properties) == 2
        name_prop = next(p for p in node.properties if p.target_name == "name")
        assert name_prop.source_field == "full_name"

        age_prop = next(p for p in node.properties if p.target_name == "age")
        assert age_prop.source_field == "age"

    def test_type_transforms_generated(self):
        cfg = load_kg_schema_from_dict(_minimal_kg_schema())
        node = cfg.nodes[0]

        age_prop = next(p for p in node.properties if p.target_name == "age")
        assert age_prop.transform is not None
        assert age_prop.transform[0].type == "to_int"

    def test_id_generation_config(self):
        cfg = load_kg_schema_from_dict(_minimal_kg_schema())
        node = cfg.nodes[0]

        assert node.id_generation is not None
        assert node.id_generation.strategy == "sha256-hash"
        assert node.id_generation.fields == ["name"]
        assert node.id_generation.hash_length == 16

    def test_schema_constraints_generated(self):
        cfg = load_kg_schema_from_dict(_minimal_kg_schema())

        assert cfg.graph_schema is not None
        assert len(cfg.graph_schema.constraints) == 1
        c = cfg.graph_schema.constraints[0]
        assert c.label == "Person"
        assert c.property == "_id"
        assert c.type == "unique"

    def test_schema_indexes_generated(self):
        cfg = load_kg_schema_from_dict(_minimal_kg_schema())

        assert cfg.graph_schema is not None
        assert len(cfg.graph_schema.indexes) == 1
        idx = cfg.graph_schema.indexes[0]
        assert idx.label == "Person"
        assert idx.properties == ["_id"]

    def test_source_configs_generated(self):
        cfg = load_kg_schema_from_dict(_minimal_kg_schema())

        assert len(cfg.sources) == 1
        src = cfg.sources[0]
        assert src.name == "src1"
        assert src.type == "json"
        assert src.path == "data/test.jsonl"

    def test_explicit_sources_override(self):
        sources = [{"name": "src1", "type": "csv", "path": "/my/data.csv"}]
        cfg = load_kg_schema_from_dict(_minimal_kg_schema(), sources=sources)

        assert cfg.sources[0].type == "csv"
        assert cfg.sources[0].path == "/my/data.csv"

    def test_neo4j_connection_override(self):
        cfg = load_kg_schema_from_dict(
            _minimal_kg_schema(),
            neo4j={"uri": "bolt://custom:7687", "database": "mydb"},
        )
        assert cfg.neo4j.uri == "bolt://custom:7687"
        assert cfg.neo4j.database == "mydb"

    def test_relationships(self):
        schema = _minimal_kg_schema(
            nodes=[
                {
                    "label": "Person",
                    "naturalKey": ["name"],
                    "idField": "_id",
                    "source": "src1",
                    "properties": {
                        "name": {"sourceField": "name", "type": "string"},
                    },
                },
                {
                    "label": "Company",
                    "naturalKey": ["company_name"],
                    "idField": "_id",
                    "source": "src1",
                    "properties": {
                        "name": {"sourceField": "company_name", "type": "string"},
                    },
                },
            ],
            relationships=[
                {
                    "type": "WORKS_AT",
                    "source": "src1",
                    "fromNode": "Person",
                    "fromKey": "_id",
                    "fromField": "person_id",
                    "toNode": "Company",
                    "toKey": "_id",
                    "toField": "company_id",
                }
            ],
        )
        cfg = load_kg_schema_from_dict(schema)

        assert len(cfg.relationships) == 1
        rel = cfg.relationships[0]
        assert rel.rel_type == "WORKS_AT"
        assert rel.from_label == "Person"
        assert rel.to_label == "Company"
        assert rel.from_key == "_id"
        assert rel.to_key == "_id"
        assert rel.from_field == "person_id"
        assert rel.to_field == "company_id"

    def test_relationship_with_properties(self):
        schema = _minimal_kg_schema(
            relationships=[
                {
                    "type": "CALLS",
                    "source": "src1",
                    "fromNode": "Method",
                    "fromKey": "_id",
                    "fromField": "caller_id",
                    "toNode": "Method",
                    "toKey": "_id",
                    "toField": "callee_id",
                    "properties": {
                        "call_count": {
                            "sourceField": "count",
                            "type": "int",
                        }
                    },
                }
            ],
        )
        cfg = load_kg_schema_from_dict(schema)

        rel = cfg.relationships[0]
        assert len(rel.properties) == 1
        assert rel.properties[0].source_field == "count"
        assert rel.properties[0].target_name == "call_count"

    def test_multiple_source_definitions(self):
        schema = _minimal_kg_schema()
        schema["sourceDefinitions"]["codeql"] = {
            "description": "CodeQL",
            "dataFormat": "JSONL files",
            "examples": ["data/codeql.jsonl"],
        }
        # Add a node from the second source
        schema["nodes"].append(
            {
                "label": "Class",
                "naturalKey": ["class_name"],
                "idField": "_id",
                "source": "codeql",
                "properties": {
                    "name": {"sourceField": "class_name", "type": "string"},
                },
            }
        )
        cfg = load_kg_schema_from_dict(schema)

        source_names = {s.name for s in cfg.sources}
        assert "src1" in source_names
        assert "codeql" in source_names

    def test_node_without_natural_key(self):
        """Nodes without naturalKey should not get id_generation."""
        schema = _minimal_kg_schema()
        schema["nodes"] = [
            {
                "label": "Tag",
                "key": "tag_name",
                "source": "src1",
                "properties": {
                    "tag_name": {
                        "sourceField": "tag_name",
                        "type": "string",
                        "required": True,
                    }
                },
            }
        ]
        cfg = load_kg_schema_from_dict(schema)

        node = cfg.nodes[0]
        assert node.id_generation is None
        assert node.key == "tag_name"

    def test_per_node_id_generation_override(self):
        """A node can override the global idGeneration."""
        schema = _minimal_kg_schema()
        schema["nodes"][0]["idGeneration"] = {
            "strategy": "sha256-hash",
            "hashLength": 32,
        }
        cfg = load_kg_schema_from_dict(schema)

        assert cfg.nodes[0].id_generation.hash_length == 32


class TestLoadKgSchemaFromFile:
    def test_load_from_json_file(self, tmp_path):
        schema = _minimal_kg_schema()
        p = tmp_path / "schema.json"
        p.write_text(json.dumps(schema))

        cfg = load_kg_schema(p)
        assert len(cfg.nodes) == 1

    def test_load_config_auto_detects_kg_schema(self, tmp_path):
        """load_config should detect KG schema and route to KG loader."""
        schema = _minimal_kg_schema()
        p = tmp_path / "schema.json"
        p.write_text(json.dumps(schema))

        cfg = load_config(p)
        assert len(cfg.nodes) == 1
        assert cfg.nodes[0].id_generation is not None


class TestIdGenerationInGraphWriter:
    def test_node_row_with_id_generation(self):
        """Verify the graph writer injects generated IDs."""
        import hashlib

        from neo4j_ingest.config import (
            IdGenerationConfig,
            NodeMapping,
            PropertyMapping,
        )
        from neo4j_ingest.graph import Neo4jWriter

        mapping = NodeMapping(
            source="src",
            label="Person",
            key="_id",
            properties=[
                PropertyMapping(source_field="full_name", target="name"),
            ],
            id_generation=IdGenerationConfig(
                strategy="sha256-hash",
                fields=["full_name"],
                hash_length=16,
            ),
        )
        record = {"full_name": "Alice"}
        row = Neo4jWriter._map_node_row(record, mapping)

        expected_id = hashlib.sha256("Alice".encode()).hexdigest()[:16]
        assert row["_id"] == expected_id
        assert row["name"] == "Alice"

    def test_node_query_uses_generated_key(self):
        from neo4j_ingest.config import (
            IdGenerationConfig,
            NodeMapping,
            PropertyMapping,
        )
        from neo4j_ingest.graph import Neo4jWriter

        mapping = NodeMapping(
            source="src",
            label="Method",
            key="_id",
            properties=[
                PropertyMapping(source_field="method_name", target="name"),
            ],
            id_generation=IdGenerationConfig(
                strategy="sha256-hash",
                fields=["repo", "class", "method_name"],
                hash_length=16,
            ),
        )
        query = Neo4jWriter._build_node_query(mapping)
        assert "MERGE (n:Method {_id: row._id})" in query
        assert "n.name = row.name" in query


class TestFullKgSchemaExample:
    def test_load_example_schema(self):
        """Load the example KG mapping schema from the examples directory."""
        from pathlib import Path

        example_path = Path(__file__).parent.parent / "examples" / "kg_mapping_schema.json"
        if not example_path.exists():
            pytest.skip("Example file not found")

        cfg = load_config(example_path)

        # Verify nodes
        labels = {n.label for n in cfg.nodes}
        assert "Repository" in labels
        assert "Package" in labels
        assert "Class" in labels
        assert "Method" in labels
        assert "Team" in labels

        # Verify relationships
        rel_types = {r.rel_type for r in cfg.relationships}
        assert "CONTAINS_PACKAGE" in rel_types
        assert "HAS_CLASS" in rel_types
        assert "HAS_METHOD" in rel_types
        assert "CALLS" in rel_types
        assert "OWNS" in rel_types

        # Verify ID generation
        for node in cfg.nodes:
            assert node.id_generation is not None
            assert node.id_generation.strategy == "sha256-hash"

        # Verify schema
        assert cfg.graph_schema is not None
        assert len(cfg.graph_schema.constraints) == 5
        assert len(cfg.graph_schema.indexes) == 5

        # Verify sources
        source_names = {s.name for s in cfg.sources}
        assert "codeql" in source_names
        assert "attributor" in source_names
