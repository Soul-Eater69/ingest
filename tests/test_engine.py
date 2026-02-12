"""Tests for the ingestion engine (mocking Neo4j and sources)."""

from unittest.mock import MagicMock, patch

from neo4j_ingest.config import (
    IngestConfig,
    JobSettings,
    Neo4jConnection,
    NodeMapping,
    PropertyMapping,
    RelationshipMapping,
    SchemaHook,
    SourceConfig,
    ValidationConfig,
    ValidationRuleConfig,
)
from neo4j_ingest.engine import run


def _make_config(**kwargs):
    defaults = dict(
        neo4j=Neo4jConnection(
            uri="bolt://localhost:7687",
            username="neo4j",
            password="test",
        ),
        settings=JobSettings(health_check=False),
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
    defaults.update(kwargs)
    return IngestConfig(**defaults)


def _mock_records():
    return [
        {"id": 1, "name": "Alice", "friend_id": 2},
        {"id": 2, "name": "Bob", "friend_id": 1},
    ]


@patch("neo4j_ingest.engine.Neo4jWriter")
@patch("neo4j_ingest.engine.read_source")
def test_run_calls_writer(mock_read_source, mock_writer_cls):
    mock_read_source.return_value = _mock_records()

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


@patch("neo4j_ingest.engine.Neo4jWriter")
@patch("neo4j_ingest.engine.read_source")
def test_run_pre_post_hooks(mock_read_source, mock_writer_cls):
    mock_read_source.return_value = _mock_records()

    mock_writer = MagicMock()
    mock_writer.write_nodes.return_value = 2
    mock_writer.write_relationships.return_value = 2
    mock_writer.__enter__ = MagicMock(return_value=mock_writer)
    mock_writer.__exit__ = MagicMock(return_value=False)
    mock_writer_cls.return_value = mock_writer

    config = _make_config(
        pre_hooks=[SchemaHook(cypher="CREATE INDEX ...")],
        post_hooks=[SchemaHook(cypher="MATCH (n) RETURN count(n)")],
    )
    run(config)

    assert mock_writer.run_hooks.call_count == 2


@patch("neo4j_ingest.engine.read_source")
def test_dry_run_skips_neo4j(mock_read_source):
    mock_read_source.return_value = _mock_records()

    config = _make_config()
    result = run(config, dry_run=True)

    assert result.total_nodes == 0
    assert result.total_relationships == 0
    assert result.metrics is not None
    assert result.metrics.status == "dry_run"


@patch("neo4j_ingest.engine.Neo4jWriter")
@patch("neo4j_ingest.engine.read_source")
def test_validation_skips_bad_records(mock_read_source, mock_writer_cls):
    mock_read_source.return_value = [
        {"id": 1, "name": "Alice", "friend_id": 2},
        {"id": None, "name": "Bad", "friend_id": 1},
    ]

    mock_writer = MagicMock()
    mock_writer.write_nodes.return_value = 1
    mock_writer.write_relationships.return_value = 1
    mock_writer.__enter__ = MagicMock(return_value=mock_writer)
    mock_writer.__exit__ = MagicMock(return_value=False)
    mock_writer_cls.return_value = mock_writer

    config = _make_config(
        nodes=[
            NodeMapping(
                source="people",
                label="Person",
                key="id",
                properties=[
                    PropertyMapping(source_field="id"),
                    PropertyMapping(source_field="name"),
                ],
                validation=ValidationConfig(
                    on_error="skip",
                    rules=[ValidationRuleConfig(field="id", rule="required")],
                ),
            ),
        ],
    )
    result = run(config)

    assert result.records_skipped == 1


@patch("neo4j_ingest.engine.Neo4jWriter")
@patch("neo4j_ingest.engine.read_source")
def test_metrics_are_populated(mock_read_source, mock_writer_cls):
    mock_read_source.return_value = _mock_records()

    mock_writer = MagicMock()
    mock_writer.write_nodes.return_value = 2
    mock_writer.write_relationships.return_value = 2
    mock_writer.__enter__ = MagicMock(return_value=mock_writer)
    mock_writer.__exit__ = MagicMock(return_value=False)
    mock_writer_cls.return_value = mock_writer

    config = _make_config()
    result = run(config)

    assert result.metrics is not None
    assert result.metrics.job_id != ""
    assert result.metrics.status == "completed"
    assert len(result.metrics.steps) >= 2
    assert result.metrics.duration_seconds >= 0
