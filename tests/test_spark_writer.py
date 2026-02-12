"""Tests for SparkNeo4jWriter (mocked — no Spark/Neo4j needed)."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from neo4j_ingest.config import (
    Neo4jConnection,
    NodeMapping,
    PropertyMapping,
    RelationshipMapping,
    SchemaHook,
)
from neo4j_ingest.spark_writer import SparkNeo4jWriter


@pytest.fixture
def connection():
    return Neo4jConnection(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="test",
        database="neo4j",
    )


@pytest.fixture
def mock_pyspark():
    """Inject a mock pyspark module so imports don't fail."""
    mock_functions = MagicMock()
    mock_col = MagicMock()
    # Make F.col() return a mock that supports .alias()
    mock_col_instance = MagicMock()
    mock_col_instance.alias.return_value = mock_col_instance
    mock_functions.col.return_value = mock_col_instance

    mock_pyspark_sql = MagicMock()
    mock_pyspark_sql.functions = mock_functions

    mock_pyspark_mod = MagicMock()
    mock_pyspark_mod.sql = mock_pyspark_sql
    mock_pyspark_mod.sql.functions = mock_functions

    modules = {
        "pyspark": mock_pyspark_mod,
        "pyspark.sql": mock_pyspark_sql,
        "pyspark.sql.functions": mock_functions,
    }

    with patch.dict(sys.modules, modules):
        yield mock_functions


class TestSparkNeo4jWriter:
    def test_init(self, connection):
        writer = SparkNeo4jWriter(connection, batch_size=10000)
        assert writer._batch_size == 10000
        assert writer._neo4j_options["url"] == "bolt://localhost:7687"
        assert writer._neo4j_options["batch.size"] == "10000"

    def test_context_manager(self, connection):
        with SparkNeo4jWriter(connection) as writer:
            assert writer is not None

    def test_node_cypher(self, connection):
        writer = SparkNeo4jWriter(connection)
        mapping = NodeMapping(
            source="s",
            label="Person",
            key="id",
            properties=[
                PropertyMapping(source_field="id"),
                PropertyMapping(source_field="name"),
            ],
        )
        cypher = writer._node_cypher(mapping)
        assert "MERGE (n:Person {id: event.id})" in cypher
        assert "n.name = event.name" in cypher

    def test_rel_cypher(self, connection):
        writer = SparkNeo4jWriter(connection)
        mapping = RelationshipMapping(
            source="s",
            rel_type="WORKS_AT",
            from_label="Person",
            from_key="id",
            from_field="person_id",
            to_label="Company",
            to_key="id",
            to_field="company_id",
            properties=[PropertyMapping(source_field="since", target="since")],
        )
        cypher = writer._rel_cypher(mapping)
        assert "MATCH (a:Person {id: event.from_val})" in cypher
        assert "MATCH (b:Company {id: event.to_val})" in cypher
        assert "MERGE (a)-[r:WORKS_AT]->(b)" in cypher
        assert "SET r.since = event.since" in cypher

    @patch("neo4j.GraphDatabase")
    def test_run_hooks(self, mock_gd, connection):
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
        mock_gd.driver.return_value = mock_driver

        writer = SparkNeo4jWriter(connection)
        hooks = [
            SchemaHook(cypher="CREATE INDEX idx1 ..."),
            SchemaHook(cypher="CREATE CONSTRAINT c1 ..."),
        ]
        writer.run_hooks(hooks)

        assert mock_session.run.call_count == 2
        mock_driver.close.assert_called_once()

    @patch("neo4j_ingest.spark_writer._get_or_create_spark")
    def test_write_nodes_creates_df(self, mock_get_spark, mock_pyspark, connection):
        mock_spark = MagicMock()
        mock_df = MagicMock()
        mock_spark.createDataFrame.return_value = mock_df
        mock_get_spark.return_value = mock_spark

        mock_df.select.return_value = mock_df
        mock_df.repartition.return_value = mock_df
        mock_df.count.return_value = 3
        mock_df.rdd.getNumPartitions.return_value = 2

        writer = SparkNeo4jWriter(connection, partitions=2)
        mapping = NodeMapping(
            source="s",
            label="Person",
            key="id",
            properties=[
                PropertyMapping(source_field="id"),
                PropertyMapping(source_field="name"),
            ],
        )

        records = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
            {"id": 3, "name": "Charlie"},
        ]
        count = writer.write_nodes(records, mapping)
        assert count == 3
        mock_spark.createDataFrame.assert_called_once_with(records)

    @patch("neo4j_ingest.spark_writer._get_or_create_spark")
    def test_write_relationships_creates_df(self, mock_get_spark, mock_pyspark, connection):
        mock_spark = MagicMock()
        mock_df = MagicMock()
        mock_spark.createDataFrame.return_value = mock_df
        mock_get_spark.return_value = mock_spark

        mock_df.select.return_value = mock_df
        mock_df.repartition.return_value = mock_df
        mock_df.count.return_value = 2
        mock_df.rdd.getNumPartitions.return_value = 1

        writer = SparkNeo4jWriter(connection, partitions=1)
        mapping = RelationshipMapping(
            source="s",
            rel_type="KNOWS",
            from_label="Person",
            from_key="id",
            from_field="person_id",
            to_label="Person",
            to_key="id",
            to_field="friend_id",
        )

        records = [
            {"person_id": 1, "friend_id": 2},
            {"person_id": 2, "friend_id": 1},
        ]
        count = writer.write_relationships(records, mapping)
        assert count == 2


class TestSparkExecution:
    def test_spark_config_defaults(self):
        from neo4j_ingest.config import IngestConfig

        data = {
            "sources": [{"name": "s1", "type": "spark_csv", "path": "/data.csv"}],
            "nodes": [
                {
                    "source": "s1",
                    "label": "Thing",
                    "key": "id",
                    "properties": [{"source_field": "id"}],
                }
            ],
            "settings": {"execution_mode": "spark"},
        }
        cfg = IngestConfig.model_validate(data)
        assert cfg.settings.execution_mode == "spark"
        assert cfg.settings.spark.app_name == "neo4j-ingest"
        assert cfg.settings.spark.neo4j_connector_batch_size == 5000

    def test_spark_config_custom(self):
        from neo4j_ingest.config import IngestConfig

        data = {
            "sources": [{"name": "s1", "type": "spark_parquet", "path": "/data/"}],
            "nodes": [
                {
                    "source": "s1",
                    "label": "Thing",
                    "key": "id",
                    "properties": [{"source_field": "id"}],
                }
            ],
            "settings": {
                "execution_mode": "spark",
                "spark": {
                    "app_name": "my-job",
                    "master": "spark://master:7077",
                    "partitions": 64,
                    "neo4j_connector_batch_size": 20000,
                    "spark_config": {
                        "spark.sql.shuffle.partitions": "200",
                    },
                },
            },
        }
        cfg = IngestConfig.model_validate(data)
        assert cfg.settings.spark.app_name == "my-job"
        assert cfg.settings.spark.master == "spark://master:7077"
        assert cfg.settings.spark.partitions == 64
        assert cfg.settings.spark.neo4j_connector_batch_size == 20000
        assert cfg.settings.spark.spark_config["spark.sql.shuffle.partitions"] == "200"
