"""Tests for the ingestion engine (mocking Neo4j and sources)."""

from unittest.mock import MagicMock, patch

from neo4j_ingest.config import (
    IngestConfig,
    Neo4jConnection,
    NodeMapping,
    PropertyMapping,
    RelationshipMapping,
    SourceConfig,
)
from neo4j_ingest.engine import run


def _make_config():
    return IngestConfig(
        neo4j=Neo4jConnection(
            uri="bolt://localhost:7687",
            username="neo4j",
            password="test",
        ),
        sources=[
            SourceConfig(name="people", type="csv", path="fake.csv"),
        ],
        nodes=[
            NodeMapping(
                source="people",
                label="Person",
                key="id",
                properties=[
                    PropertyMapping(source_field="id"),
                    PropertyMapping(source_field="name"),
                ],
            ),
        ],
        relationships=[
            RelationshipMapping(
                source="people",
                rel_type="KNOWS",
                from_label="Person",
                from_key="id",
                from_field="id",
                to_label="Person",
                to_key="id",
                to_field="friend_id",
            ),
        ],
    )


@patch("neo4j_ingest.engine.Neo4jWriter")
@patch("neo4j_ingest.engine.read_source")
def test_run_calls_writer(mock_read_source, mock_writer_cls):
    mock_read_source.return_value = [
        {"id": 1, "name": "Alice", "friend_id": 2},
        {"id": 2, "name": "Bob", "friend_id": 1},
    ]

    mock_writer = MagicMock()
    mock_writer.write_nodes.return_value = 2
    mock_writer.write_relationships.return_value = 2
    mock_writer.__enter__ = MagicMock(return_value=mock_writer)
    mock_writer.__exit__ = MagicMock(return_value=False)
    mock_writer_cls.return_value = mock_writer

    config = _make_config()
    result = run(config)

    assert result.total_nodes == 2
    assert result.total_relationships == 2
    mock_writer.write_nodes.assert_called_once()
    mock_writer.write_relationships.assert_called_once()
