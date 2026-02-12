"""Tests for Spark source connectors (mocked — PySpark not required)."""

from unittest.mock import MagicMock, patch

import pytest

from neo4j_ingest.config import SourceConfig


@pytest.fixture
def mock_spark_session():
    """Mock SparkSession and inject it into spark_sources."""
    mock_spark = MagicMock()
    with patch(
        "neo4j_ingest.spark_sources._get_or_create_spark",
        return_value=mock_spark,
    ):
        yield mock_spark


class TestSparkCsv:
    def test_read_spark_csv(self, mock_spark_session):
        from neo4j_ingest.spark_sources import read_spark_csv

        mock_row1 = MagicMock()
        mock_row1.asDict.return_value = {"id": 1, "name": "Alice"}
        mock_row2 = MagicMock()
        mock_row2.asDict.return_value = {"id": 2, "name": "Bob"}

        mock_df = MagicMock()
        mock_df.collect.return_value = [mock_row1, mock_row2]
        mock_spark_session.read.options.return_value.csv.return_value = mock_df

        cfg = SourceConfig(name="test", type="spark_csv", path="s3a://bucket/data.csv")
        records = read_spark_csv(cfg)

        assert len(records) == 2
        assert records[0] == {"id": 1, "name": "Alice"}
        mock_spark_session.read.options.return_value.csv.assert_called_once_with(
            "s3a://bucket/data.csv"
        )


class TestSparkJson:
    def test_read_spark_json(self, mock_spark_session):
        from neo4j_ingest.spark_sources import read_spark_json

        mock_row = MagicMock()
        mock_row.asDict.return_value = {"id": 1}
        mock_df = MagicMock()
        mock_df.collect.return_value = [mock_row]
        mock_spark_session.read.options.return_value.json.return_value = mock_df

        cfg = SourceConfig(name="test", type="spark_json", path="/data/*.json")
        records = read_spark_json(cfg)

        assert len(records) == 1


class TestSparkParquet:
    def test_read_spark_parquet(self, mock_spark_session):
        from neo4j_ingest.spark_sources import read_spark_parquet

        mock_row = MagicMock()
        mock_row.asDict.return_value = {"id": 1, "value": 99.9}
        mock_df = MagicMock()
        mock_df.collect.return_value = [mock_row]
        mock_spark_session.read.parquet.return_value = mock_df

        cfg = SourceConfig(name="test", type="spark_parquet", path="s3a://bucket/data/")
        records = read_spark_parquet(cfg)

        assert len(records) == 1
        assert records[0]["value"] == 99.9

    def test_read_spark_parquet_with_sql_filter(self, mock_spark_session):
        from neo4j_ingest.spark_sources import read_spark_parquet

        mock_row = MagicMock()
        mock_row.asDict.return_value = {"id": 1}
        mock_filtered = MagicMock()
        mock_filtered.collect.return_value = [mock_row]

        mock_df = MagicMock()
        mock_spark_session.read.parquet.return_value = mock_df
        mock_spark_session.sql.return_value = mock_filtered

        cfg = SourceConfig(
            name="test",
            type="spark_parquet",
            path="/data/",
            query="SELECT * FROM __test WHERE id > 0",
        )
        records = read_spark_parquet(cfg)

        assert len(records) == 1
        mock_df.createOrReplaceTempView.assert_called_once_with("__test")
        mock_spark_session.sql.assert_called_once()


class TestSparkDelta:
    def test_read_spark_delta(self, mock_spark_session):
        from neo4j_ingest.spark_sources import read_spark_delta

        mock_row = MagicMock()
        mock_row.asDict.return_value = {"customer_id": "C001"}
        mock_df = MagicMock()
        mock_df.collect.return_value = [mock_row]
        mock_spark_session.read.format.return_value.load.return_value = mock_df

        cfg = SourceConfig(name="test", type="spark_delta", path="s3a://bucket/delta/")
        records = read_spark_delta(cfg)

        assert records[0]["customer_id"] == "C001"
        mock_spark_session.read.format.assert_called_once_with("delta")


class TestSparkJdbc:
    def test_read_spark_jdbc(self, mock_spark_session):
        from neo4j_ingest.spark_sources import read_spark_jdbc

        mock_row = MagicMock()
        mock_row.asDict.return_value = {"id": 1}
        mock_df = MagicMock()
        mock_df.collect.return_value = [mock_row]
        mock_spark_session.read.format.return_value.options.return_value.load.return_value = mock_df

        cfg = SourceConfig(
            name="test",
            type="spark_jdbc",
            connection_string="jdbc:postgresql://localhost:5432/db",
            query="SELECT * FROM users",
            headers={"driver": "org.postgresql.Driver"},
        )
        records = read_spark_jdbc(cfg)

        assert len(records) == 1
        mock_spark_session.read.format.assert_called_once_with("jdbc")


class TestSparkTable:
    def test_read_spark_table(self, mock_spark_session):
        from neo4j_ingest.spark_sources import read_spark_table

        mock_row = MagicMock()
        mock_row.asDict.return_value = {"col": "val"}
        mock_df = MagicMock()
        mock_df.collect.return_value = [mock_row]
        mock_spark_session.table.return_value = mock_df

        cfg = SourceConfig(
            name="test",
            type="spark_table",
            query="catalog.schema.my_table",
        )
        records = read_spark_table(cfg)

        assert len(records) == 1
        mock_spark_session.table.assert_called_once_with("catalog.schema.my_table")

    def test_read_spark_table_with_sql(self, mock_spark_session):
        from neo4j_ingest.spark_sources import read_spark_table

        mock_row = MagicMock()
        mock_row.asDict.return_value = {"id": 1}
        mock_df = MagicMock()
        mock_df.collect.return_value = [mock_row]
        mock_spark_session.sql.return_value = mock_df

        cfg = SourceConfig(
            name="test",
            type="spark_table",
            query="SELECT * FROM catalog.schema.my_table WHERE active = true",
        )
        records = read_spark_table(cfg)

        assert len(records) == 1
        mock_spark_session.sql.assert_called_once()
