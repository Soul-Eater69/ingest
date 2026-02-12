"""Neo4j graph connector.

Handles writing nodes and relationships to Neo4j using batched MERGE
operations for efficiency and idempotency.
"""

from __future__ import annotations

import logging
from typing import Any

from neo4j import GraphDatabase

from neo4j_ingest.config import (
    Neo4jConnection,
    NodeMapping,
    PropertyMapping,
    RelationshipMapping,
)

logger = logging.getLogger(__name__)

Record = dict[str, Any]

DEFAULT_BATCH_SIZE = 500


class Neo4jWriter:
    """Manages a Neo4j driver and provides batch write methods."""

    def __init__(self, connection: Neo4jConnection) -> None:
        self._connection = connection
        self._driver = GraphDatabase.driver(
            connection.uri,
            auth=(connection.username, connection.password),
        )
        logger.info("Connected to Neo4j at %s", connection.uri)

    def close(self) -> None:
        self._driver.close()
        logger.info("Neo4j connection closed")

    def __enter__(self) -> "Neo4jWriter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- Node writing --------------------------------------------------------

    @staticmethod
    def _build_node_query(mapping: NodeMapping) -> str:
        """Build a parameterised Cypher MERGE query for nodes.

        Example output:
            UNWIND $rows AS row
            MERGE (n:Person {id: row.id})
            SET n.name = row.name, n.age = row.age
        """
        set_clauses = ", ".join(
            f"n.{p.target_name} = row.{p.target_name}" for p in mapping.properties
        )
        query = (
            f"UNWIND $rows AS row "
            f"MERGE (n:{mapping.label} {{{mapping.key}: row.{mapping.key}}}) "
        )
        if set_clauses:
            query += f"SET {set_clauses}"
        return query

    @staticmethod
    def _map_node_row(record: Record, mapping: NodeMapping) -> Record:
        """Extract the fields needed for a single node from a source record."""
        row: Record = {}
        for prop in mapping.properties:
            row[prop.target_name] = record.get(prop.source_field)
        # Ensure the key field is always present
        if mapping.key not in row:
            key_field = next(
                (p.source_field for p in mapping.properties if p.target_name == mapping.key),
                mapping.key,
            )
            row[mapping.key] = record.get(key_field)
        return row

    def write_nodes(
        self,
        records: list[Record],
        mapping: NodeMapping,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> int:
        """Write nodes to Neo4j in batches. Returns the total number of rows processed."""
        query = self._build_node_query(mapping)
        rows = [self._map_node_row(r, mapping) for r in records]
        total = 0

        with self._driver.session(database=self._connection.database) as session:
            for i in range(0, len(rows), batch_size):
                batch = rows[i : i + batch_size]
                session.run(query, rows=batch)
                total += len(batch)
                logger.debug(
                    "Wrote batch of %d %s nodes (%d/%d)",
                    len(batch), mapping.label, total, len(rows),
                )

        logger.info(
            "Created/merged %d %s nodes", total, mapping.label,
        )
        return total

    # -- Relationship writing ------------------------------------------------

    @staticmethod
    def _build_rel_query(mapping: RelationshipMapping) -> str:
        """Build a parameterised Cypher MERGE query for relationships.

        Example output:
            UNWIND $rows AS row
            MATCH (a:Person {id: row.from_val})
            MATCH (b:Company {id: row.to_val})
            MERGE (a)-[r:WORKS_AT]->(b)
            SET r.since = row.since
        """
        query = (
            f"UNWIND $rows AS row "
            f"MATCH (a:{mapping.from_label} {{{mapping.from_key}: row.from_val}}) "
            f"MATCH (b:{mapping.to_label} {{{mapping.to_key}: row.to_val}}) "
            f"MERGE (a)-[r:{mapping.rel_type}]->(b)"
        )
        if mapping.properties:
            set_clauses = ", ".join(
                f"r.{p.target_name} = row.{p.target_name}" for p in mapping.properties
            )
            query += f" SET {set_clauses}"
        return query

    @staticmethod
    def _map_rel_row(
        record: Record, mapping: RelationshipMapping
    ) -> Record:
        """Extract the fields needed for a single relationship."""
        row: Record = {
            "from_val": record.get(mapping.from_field),
            "to_val": record.get(mapping.to_field),
        }
        for prop in mapping.properties:
            row[prop.target_name] = record.get(prop.source_field)
        return row

    def write_relationships(
        self,
        records: list[Record],
        mapping: RelationshipMapping,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> int:
        """Write relationships to Neo4j in batches. Returns total rows processed."""
        query = self._build_rel_query(mapping)
        rows = [self._map_rel_row(r, mapping) for r in records]
        total = 0

        with self._driver.session(database=self._connection.database) as session:
            for i in range(0, len(rows), batch_size):
                batch = rows[i : i + batch_size]
                session.run(query, rows=batch)
                total += len(batch)
                logger.debug(
                    "Wrote batch of %d %s rels (%d/%d)",
                    len(batch), mapping.rel_type, total, len(rows),
                )

        logger.info(
            "Created/merged %d %s relationships", total, mapping.rel_type,
        )
        return total
