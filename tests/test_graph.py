"""Tests for Neo4j graph writer (query generation and row mapping)."""

from neo4j_ingest.config import (
    NodeMapping,
    PropertyMapping,
    RelationshipMapping,
    TransformConfig,
)
from neo4j_ingest.graph import Neo4jWriter


class TestBuildNodeQuery:
    def test_basic_node_query(self):
        mapping = NodeMapping(
            source="s",
            label="Person",
            key="id",
            properties=[
                PropertyMapping(source_field="id"),
                PropertyMapping(source_field="full_name", target="name"),
            ],
        )
        query = Neo4jWriter._build_node_query(mapping)
        assert "MERGE (n:Person {id: row.id})" in query
        assert "n.name = row.name" in query
        assert "UNWIND $rows AS row" in query

    def test_node_row_mapping(self):
        mapping = NodeMapping(
            source="s",
            label="Person",
            key="id",
            properties=[
                PropertyMapping(source_field="id"),
                PropertyMapping(source_field="full_name", target="name"),
            ],
        )
        record = {"id": 42, "full_name": "Alice", "extra": "ignored"}
        row = Neo4jWriter._map_node_row(record, mapping)
        assert row == {"id": 42, "name": "Alice"}

    def test_node_row_mapping_with_transform(self):
        mapping = NodeMapping(
            source="s",
            label="Person",
            key="id",
            properties=[
                PropertyMapping(source_field="id", transform=TransformConfig(type="to_int")),
                PropertyMapping(
                    source_field="full_name",
                    target="name",
                    transform=TransformConfig(type="uppercase"),
                ),
            ],
        )
        record = {"id": "42", "full_name": "Alice"}
        row = Neo4jWriter._map_node_row(record, mapping)
        assert row == {"id": 42, "name": "ALICE"}

    def test_node_row_mapping_with_transform_chain(self):
        mapping = NodeMapping(
            source="s",
            label="Person",
            key="id",
            properties=[
                PropertyMapping(source_field="id"),
                PropertyMapping(
                    source_field="name",
                    transform=[
                        TransformConfig(type="strip"),
                        TransformConfig(type="uppercase"),
                    ],
                ),
            ],
        )
        record = {"id": 1, "name": "  alice  "}
        row = Neo4jWriter._map_node_row(record, mapping)
        assert row == {"id": 1, "name": "ALICE"}


class TestBuildRelQuery:
    def test_basic_rel_query(self):
        mapping = RelationshipMapping(
            source="s",
            rel_type="WORKS_AT",
            from_label="Person",
            from_key="id",
            from_field="person_id",
            to_label="Company",
            to_key="id",
            to_field="company_id",
        )
        query = Neo4jWriter._build_rel_query(mapping)
        assert "MATCH (a:Person {id: row.from_val})" in query
        assert "MATCH (b:Company {id: row.to_val})" in query
        assert "MERGE (a)-[r:WORKS_AT]->(b)" in query

    def test_rel_with_properties(self):
        mapping = RelationshipMapping(
            source="s",
            rel_type="WORKS_AT",
            from_label="Person",
            from_key="id",
            from_field="person_id",
            to_label="Company",
            to_key="id",
            to_field="company_id",
            properties=[PropertyMapping(source_field="start_date", target="since")],
        )
        query = Neo4jWriter._build_rel_query(mapping)
        assert "SET r.since = row.since" in query

    def test_rel_row_mapping(self):
        mapping = RelationshipMapping(
            source="s",
            rel_type="WORKS_AT",
            from_label="Person",
            from_key="id",
            from_field="person_id",
            to_label="Company",
            to_key="id",
            to_field="company_id",
            properties=[PropertyMapping(source_field="start_date", target="since")],
        )
        record = {"person_id": 1, "company_id": 99, "start_date": "2023-01-01"}
        row = Neo4jWriter._map_rel_row(record, mapping)
        assert row == {"from_val": 1, "to_val": 99, "since": "2023-01-01"}

    def test_rel_row_mapping_with_transform(self):
        mapping = RelationshipMapping(
            source="s",
            rel_type="WORKS_AT",
            from_label="Person",
            from_key="id",
            from_field="person_id",
            to_label="Company",
            to_key="id",
            to_field="company_id",
            properties=[
                PropertyMapping(
                    source_field="start_date",
                    target="since",
                    transform=TransformConfig(
                        type="to_datetime",
                        params={"format": "%Y-%m-%d"},
                    ),
                )
            ],
        )
        record = {"person_id": 1, "company_id": 99, "start_date": "2023-01-01"}
        row = Neo4jWriter._map_rel_row(record, mapping)
        assert row["since"] == "2023-01-01T00:00:00"
