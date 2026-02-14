"""Tests for declarative Neo4j schema (constraints and indexes)."""

from neo4j_ingest.config import (
    IngestConfig,
    SchemaConstraint,
    SchemaDefinition,
    SchemaIndex,
)


class TestSchemaConstraint:
    def test_unique_constraint_cypher(self):
        c = SchemaConstraint(label="Person", property="emp_id", type="unique")
        cypher = c.to_cypher()
        assert "CREATE CONSTRAINT" in cypher
        assert "IF NOT EXISTS" in cypher
        assert "Person" in cypher
        assert "emp_id" in cypher
        assert "IS UNIQUE" in cypher

    def test_exists_constraint_cypher(self):
        c = SchemaConstraint(label="Person", property="email", type="exists")
        cypher = c.to_cypher()
        assert "IS NOT NULL" in cypher
        assert "Person" in cypher
        assert "email" in cypher

    def test_node_key_constraint_cypher(self):
        c = SchemaConstraint(
            label="Person", property=["first_name", "last_name"], type="node_key"
        )
        cypher = c.to_cypher()
        assert "IS NODE KEY" in cypher
        assert "n.first_name" in cypher
        assert "n.last_name" in cypher

    def test_custom_constraint_name(self):
        c = SchemaConstraint(
            label="Person", property="id", type="unique", name="my_constraint"
        )
        cypher = c.to_cypher()
        assert "my_constraint" in cypher

    def test_auto_generated_constraint_name(self):
        c = SchemaConstraint(label="Person", property="emp_id", type="unique")
        cypher = c.to_cypher()
        assert "person_emp_id_unique" in cypher

    def test_composite_unique_constraint(self):
        c = SchemaConstraint(
            label="Event", property=["date", "venue"], type="unique"
        )
        cypher = c.to_cypher()
        assert "n.date" in cypher
        assert "n.venue" in cypher
        assert "IS UNIQUE" in cypher


class TestSchemaIndex:
    def test_range_index_cypher(self):
        idx = SchemaIndex(label="Person", properties=["email"], type="range")
        cypher = idx.to_cypher()
        assert "CREATE RANGE INDEX" in cypher
        assert "IF NOT EXISTS" in cypher
        assert "Person" in cypher
        assert "n.email" in cypher

    def test_text_index_cypher(self):
        idx = SchemaIndex(label="Person", properties=["name"], type="text")
        cypher = idx.to_cypher()
        assert "CREATE TEXT INDEX" in cypher

    def test_fulltext_index_cypher(self):
        idx = SchemaIndex(
            label="Article", properties=["title", "body"], type="fulltext"
        )
        cypher = idx.to_cypher()
        assert "CREATE FULLTEXT INDEX" in cypher
        assert "n.title" in cypher
        assert "n.body" in cypher

    def test_btree_index_no_type_prefix(self):
        idx = SchemaIndex(label="Person", properties=["age"], type="btree")
        cypher = idx.to_cypher()
        # btree should not have a type prefix
        assert "CREATE INDEX" in cypher
        assert "BTREE" not in cypher

    def test_composite_index(self):
        idx = SchemaIndex(
            label="Person", properties=["first_name", "last_name"], type="range"
        )
        cypher = idx.to_cypher()
        assert "n.first_name" in cypher
        assert "n.last_name" in cypher

    def test_custom_index_name(self):
        idx = SchemaIndex(
            label="Person", properties=["email"], type="range", name="my_idx"
        )
        cypher = idx.to_cypher()
        assert "my_idx" in cypher

    def test_auto_generated_index_name(self):
        idx = SchemaIndex(label="Person", properties=["email"], type="range")
        cypher = idx.to_cypher()
        assert "idx_person_email" in cypher


class TestSchemaDefinition:
    def test_to_hooks_generates_hooks(self):
        schema = SchemaDefinition(
            constraints=[
                SchemaConstraint(label="Person", property="id", type="unique"),
            ],
            indexes=[
                SchemaIndex(label="Person", properties=["email"], type="range"),
            ],
        )
        hooks = schema.to_hooks()
        assert len(hooks) == 2
        assert "CREATE CONSTRAINT" in hooks[0].cypher
        assert "CREATE" in hooks[1].cypher
        assert hooks[0].description != ""
        assert hooks[1].description != ""

    def test_empty_schema_produces_no_hooks(self):
        schema = SchemaDefinition()
        hooks = schema.to_hooks()
        assert hooks == []


class TestSchemaInConfig:
    def test_config_with_schema(self):
        data = {
            "sources": [{"name": "s1", "type": "csv", "path": "data.csv"}],
            "nodes": [
                {
                    "source": "s1",
                    "label": "Thing",
                    "key": "id",
                    "properties": [{"source_field": "id"}],
                }
            ],
            "schema": {
                "constraints": [
                    {"label": "Thing", "property": "id", "type": "unique"}
                ],
                "indexes": [
                    {"label": "Thing", "properties": ["name"], "type": "range"}
                ],
            },
        }
        cfg = IngestConfig.model_validate(data)
        assert cfg.graph_schema is not None
        assert len(cfg.graph_schema.constraints) == 1
        assert len(cfg.graph_schema.indexes) == 1

    def test_config_without_schema_is_none(self):
        data = {
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
        cfg = IngestConfig.model_validate(data)
        assert cfg.graph_schema is None
