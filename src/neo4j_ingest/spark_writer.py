"""Spark-based Neo4j writer using the Neo4j Spark Connector.

Instead of sending records through the Python Neo4j driver one batch at a time,
this writer keeps data distributed across the Spark cluster and writes to Neo4j
in parallel from every executor. This is the key to scaling to billions of rows.

Architecture:
    [Spark Executors] --parallel--> [Neo4j Cluster]

The Neo4j Spark Connector (org.neo4j:neo4j-connector-apache-spark) is a
JVM library that ships as a Spark package. It must be available on the
Spark classpath — typically via:
    spark.jars.packages=org.neo4j:neo4j-connector-apache-spark_2.12:5.3.1_for_spark_3

Usage:
    This module is used automatically when the engine detects Spark sources
    and the SparkWriter is configured, or it can be used directly:

        from neo4j_ingest.spark_writer import SparkNeo4jWriter

        writer = SparkNeo4jWriter(config.neo4j)
        writer.write_nodes_df(dataframe, node_mapping)

Requires: pip install neo4j-ingest[spark]
"""

from __future__ import annotations

import logging
from typing import Any

from neo4j_ingest.config import (
    Neo4jConnection,
    NodeMapping,
    PropertyMapping,
    RelationshipMapping,
    SchemaHook,
)

logger = logging.getLogger(__name__)

Record = dict[str, Any]


def _get_or_create_spark():
    """Get or create the active SparkSession."""
    try:
        from pyspark.sql import SparkSession
    except ImportError:
        raise ImportError(
            "PySpark is required for SparkNeo4jWriter. "
            "Install it with: pip install neo4j-ingest[spark]"
        )
    return SparkSession.builder.getOrCreate()


class SparkNeo4jWriter:
    """Writes Spark DataFrames to Neo4j using the Neo4j Spark Connector.

    This bypasses the Python driver entirely — data flows directly from
    Spark executors to Neo4j via the JVM connector, achieving full
    cluster-level parallelism.
    """

    def __init__(
        self,
        connection: Neo4jConnection,
        batch_size: int = 5000,
        partitions: int | None = None,
    ) -> None:
        self._connection = connection
        self._batch_size = batch_size
        self._partitions = partitions
        self._neo4j_options = {
            "url": connection.uri,
            "authentication.type": "basic",
            "authentication.basic.username": connection.username,
            "authentication.basic.password": connection.password,
            "database": connection.database,
            "batch.size": str(batch_size),
        }
        logger.info(
            "SparkNeo4jWriter initialised for %s (batch_size=%d)",
            connection.uri,
            batch_size,
        )

    def close(self) -> None:
        pass  # No persistent connection to close — writes are per-job

    def __enter__(self) -> "SparkNeo4jWriter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- Hooks ---------------------------------------------------------------

    def run_hooks(self, hooks: list[SchemaHook]) -> None:
        """Run Cypher hooks via the standard Python driver (single-shot)."""
        if not hooks:
            return
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            self._connection.uri,
            auth=(self._connection.username, self._connection.password),
        )
        with driver.session(database=self._connection.database) as session:
            for hook in hooks:
                desc = hook.description or hook.cypher[:60]
                logger.info("Running hook: %s", desc)
                session.run(hook.cypher)
        driver.close()

    # -- Node writing --------------------------------------------------------

    def _node_cypher(self, mapping: NodeMapping) -> str:
        """Build the Cypher template for the Spark Connector's 'query' write mode."""
        set_clauses = ", ".join(
            f"n.{p.target_name} = event.{p.target_name}"
            for p in mapping.properties
        )
        query = (
            f"MERGE (n:{mapping.label} {{{mapping.key}: event.{mapping.key}}}) "
        )
        if set_clauses:
            query += f"SET {set_clauses}"
        return query

    def write_nodes_df(self, df: Any, mapping: NodeMapping) -> int:
        """Write nodes to Neo4j directly from a Spark DataFrame.

        Uses the Neo4j Spark Connector's 'query' write mode for full MERGE
        control, running across all Spark partitions in parallel.
        """
        from pyspark.sql import functions as F

        # Build the column selection: rename source_field -> target_name
        select_cols = []
        for prop in mapping.properties:
            col_expr = F.col(prop.source_field)
            if prop.target_name != prop.source_field:
                col_expr = col_expr.alias(prop.target_name)
            select_cols.append(col_expr)

        prepared = df.select(*select_cols)

        if self._partitions:
            prepared = prepared.repartition(self._partitions)

        count = prepared.count()
        cypher = self._node_cypher(mapping)

        logger.info(
            "Writing %d %s nodes via Spark Connector (%d partitions)",
            count,
            mapping.label,
            prepared.rdd.getNumPartitions(),
        )

        (
            prepared.write
            .format("org.neo4j.spark.DataSource")
            .mode("Overwrite")
            .options(**self._neo4j_options)
            .option("query", cypher)
            .save()
        )

        logger.info("Created/merged %d %s nodes via Spark", count, mapping.label)
        return count

    def write_nodes(
        self,
        records: list[Record],
        mapping: NodeMapping,
        batch_size: int = 5000,
    ) -> int:
        """Write nodes from a list of dicts by converting to a DataFrame first.

        For small datasets this adds overhead — use the standard Neo4jWriter
        instead. This method exists for API compatibility.
        """
        spark = _get_or_create_spark()
        df = spark.createDataFrame(records)
        return self.write_nodes_df(df, mapping)

    # -- Relationship writing ------------------------------------------------

    def _rel_cypher(self, mapping: RelationshipMapping) -> str:
        """Build the Cypher template for relationship writes."""
        query = (
            f"MATCH (a:{mapping.from_label} {{{mapping.from_key}: event.from_val}}) "
            f"MATCH (b:{mapping.to_label} {{{mapping.to_key}: event.to_val}}) "
            f"MERGE (a)-[r:{mapping.rel_type}]->(b)"
        )
        if mapping.properties:
            set_clauses = ", ".join(
                f"r.{p.target_name} = event.{p.target_name}"
                for p in mapping.properties
            )
            query += f" SET {set_clauses}"
        return query

    def write_relationships_df(self, df: Any, mapping: RelationshipMapping) -> int:
        """Write relationships to Neo4j directly from a Spark DataFrame."""
        from pyspark.sql import functions as F

        select_cols = [
            F.col(mapping.from_field).alias("from_val"),
            F.col(mapping.to_field).alias("to_val"),
        ]
        for prop in mapping.properties:
            col_expr = F.col(prop.source_field)
            if prop.target_name != prop.source_field:
                col_expr = col_expr.alias(prop.target_name)
            select_cols.append(col_expr)

        prepared = df.select(*select_cols)

        if self._partitions:
            prepared = prepared.repartition(self._partitions)

        count = prepared.count()
        cypher = self._rel_cypher(mapping)

        logger.info(
            "Writing %d %s rels via Spark Connector (%d partitions)",
            count,
            mapping.rel_type,
            prepared.rdd.getNumPartitions(),
        )

        (
            prepared.write
            .format("org.neo4j.spark.DataSource")
            .mode("Overwrite")
            .options(**self._neo4j_options)
            .option("query", cypher)
            .save()
        )

        logger.info("Created/merged %d %s relationships via Spark", count, mapping.rel_type)
        return count

    def write_relationships(
        self,
        records: list[Record],
        mapping: RelationshipMapping,
        batch_size: int = 5000,
    ) -> int:
        """Write relationships from a list of dicts (API compatibility)."""
        spark = _get_or_create_spark()
        df = spark.createDataFrame(records)
        return self.write_relationships_df(df, mapping)
