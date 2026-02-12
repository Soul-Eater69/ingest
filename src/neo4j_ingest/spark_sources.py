"""Spark-based source connectors for distributed data reading.

When dealing with datasets too large for single-machine memory (multi-GB CSVs,
Parquet data lakes, Delta Lake tables, billions of SQL rows), Spark provides
distributed reading across a cluster.

These connectors register with the plugin registry so they are available
when ``pyspark`` is installed:

    sources:
      - name: huge_csv
        type: spark_csv
        path: s3a://bucket/data/*.csv

      - name: delta_table
        type: spark_delta
        path: s3a://bucket/delta/customers

      - name: catalog_table
        type: spark_table
        table: catalog.schema.customers

Requires: pip install neo4j-ingest[spark]
"""

from __future__ import annotations

import logging
from typing import Any

from neo4j_ingest.config import SourceConfig
from neo4j_ingest.registry import source_registry

logger = logging.getLogger(__name__)

Record = dict[str, Any]


def _get_or_create_spark():
    """Get or create the active SparkSession."""
    try:
        from pyspark.sql import SparkSession
    except ImportError:
        raise ImportError(
            "PySpark is required for Spark source types. "
            "Install it with: pip install neo4j-ingest[spark]"
        )

    spark = SparkSession.builder.getOrCreate()
    return spark


def _df_to_records(df: Any, limit: int | None = None) -> list[Record]:
    """Convert a Spark DataFrame to a list of dicts.

    For very large DataFrames, consider using the SparkWriter instead
    which writes directly from DataFrame to Neo4j via the Spark Connector.
    """
    if limit:
        df = df.limit(limit)
    # .collect() brings data to driver — for direct-to-Neo4j writes,
    # use SparkWriter which keeps data distributed
    return [row.asDict() for row in df.collect()]


# ---------------------------------------------------------------------------
# Spark source readers
# ---------------------------------------------------------------------------

@source_registry.register("spark_csv")
def read_spark_csv(config: SourceConfig) -> list[Record]:
    """Read CSV files via Spark (supports glob patterns, S3, HDFS, GCS)."""
    spark = _get_or_create_spark()
    logger.info("Reading Spark CSV source '%s' from %s", config.name, config.path)

    options = {
        "header": "true",
        "inferSchema": "true",
        "encoding": config.encoding,
        "delimiter": config.delimiter,
    }
    # Merge any extra Spark options from headers dict (repurposed for Spark options)
    options.update(config.headers)

    df = spark.read.options(**options).csv(config.path)
    records = _df_to_records(df)
    logger.info("Read %d records from Spark CSV '%s'", len(records), config.name)
    return records


@source_registry.register("spark_json")
def read_spark_json(config: SourceConfig) -> list[Record]:
    """Read JSON files via Spark (supports glob patterns, cloud storage)."""
    spark = _get_or_create_spark()
    logger.info("Reading Spark JSON source '%s' from %s", config.name, config.path)

    options = dict(config.headers)
    df = spark.read.options(**options).json(config.path)
    records = _df_to_records(df)
    logger.info("Read %d records from Spark JSON '%s'", len(records), config.name)
    return records


@source_registry.register("spark_parquet")
def read_spark_parquet(config: SourceConfig) -> list[Record]:
    """Read Parquet files via Spark (columnar, compressed, partitioned)."""
    spark = _get_or_create_spark()
    logger.info("Reading Spark Parquet source '%s' from %s", config.name, config.path)

    df = spark.read.parquet(config.path)

    # Apply optional SQL filter if query is provided
    if config.query:
        df.createOrReplaceTempView(f"__{config.name}")
        df = spark.sql(config.query)

    records = _df_to_records(df)
    logger.info("Read %d records from Spark Parquet '%s'", len(records), config.name)
    return records


@source_registry.register("spark_delta")
def read_spark_delta(config: SourceConfig) -> list[Record]:
    """Read Delta Lake tables via Spark (ACID, time travel, schema evolution)."""
    spark = _get_or_create_spark()
    logger.info("Reading Spark Delta source '%s' from %s", config.name, config.path)

    df = spark.read.format("delta").load(config.path)

    if config.query:
        df.createOrReplaceTempView(f"__{config.name}")
        df = spark.sql(config.query)

    records = _df_to_records(df)
    logger.info("Read %d records from Spark Delta '%s'", len(records), config.name)
    return records


@source_registry.register("spark_jdbc")
def read_spark_jdbc(config: SourceConfig) -> list[Record]:
    """Read from any JDBC database via Spark (distributed, parallel partitions).

    Config:
        connection_string: JDBC URL
        query: SQL query or table name
        headers: extra JDBC options (numPartitions, fetchsize, etc.)
    """
    spark = _get_or_create_spark()
    logger.info("Reading Spark JDBC source '%s'", config.name)

    options = {
        "url": config.connection_string,
        "driver": config.headers.get("driver", ""),
    }
    options.update(config.headers)

    if config.query and config.query.strip().upper().startswith("SELECT"):
        options["query"] = config.query
    else:
        options["dbtable"] = config.query

    df = spark.read.format("jdbc").options(**options).load()
    records = _df_to_records(df)
    logger.info("Read %d records from Spark JDBC '%s'", len(records), config.name)
    return records


@source_registry.register("spark_table")
def read_spark_table(config: SourceConfig) -> list[Record]:
    """Read from a Spark catalog table (Hive metastore, Databricks Unity Catalog).

    Config:
        query: Full table name (e.g., 'catalog.schema.table') or SQL query
    """
    spark = _get_or_create_spark()
    table_ref = config.query or config.path
    logger.info("Reading Spark table source '%s' from %s", config.name, table_ref)

    if table_ref and table_ref.strip().upper().startswith("SELECT"):
        df = spark.sql(table_ref)
    else:
        df = spark.table(table_ref)

    records = _df_to_records(df)
    logger.info("Read %d records from Spark table '%s'", len(records), config.name)
    return records
