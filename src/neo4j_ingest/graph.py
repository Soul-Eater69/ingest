"""Neo4j graph connector.

Handles writing nodes and relationships to Neo4j using batched MERGE
operations with:
- Per-field transforms
- Connection pooling
- Retry on transient failures
- Progress reporting
- Pre/post schema hooks (indexes, constraints)
"""

from __future__ import annotations

import logging
from typing import Any

from neo4j import GraphDatabase
from neo4j.exceptions import TransientError, ServiceUnavailable

from neo4j_ingest.config import (
    Neo4jConnection,
    NodeMapping,
    PropertyMapping,
    RelationshipMapping,
    SchemaDefinition,
    SchemaHook,
    TransformConfig,
)
from neo4j_ingest.id_generation import IdGenerationConfig
from neo4j_ingest.metrics import ProgressReporter
from neo4j_ingest.resilience import retry
from neo4j_ingest.transforms import apply_transforms

logger = logging.getLogger(__name__)

Record = dict[str, Any]

DEFAULT_BATCH_SIZE = 500

# Exceptions we consider retryable at the Neo4j level
_RETRYABLE = (TransientError, ServiceUnavailable, OSError)


def _extract_transform_config(prop: PropertyMapping) -> list[dict] | dict | None:
    """Convert Pydantic TransformConfig(s) to plain dicts for apply_transforms."""
    if prop.transform is None:
        return None
    if isinstance(prop.transform, list):
        return [{"type": t.type, "params": t.params} for t in prop.transform]
    return {"type": prop.transform.type, "params": prop.transform.params}


class Neo4jWriter:
    """Manages a Neo4j driver and provides batch write methods."""

    def __init__(
        self,
        connection: Neo4jConnection,
        retry_max_attempts: int = 3,
        retry_base_delay: float = 1.0,
    ) -> None:
        self._connection = connection
        self._retry_max_attempts = retry_max_attempts
        self._retry_base_delay = retry_base_delay
        self._driver = GraphDatabase.driver(
            connection.uri,
            auth=(connection.username, connection.password),
            max_connection_pool_size=connection.max_connection_pool_size,
            connection_acquisition_timeout=connection.connection_acquisition_timeout,
            encrypted=connection.encrypted,
        )
        logger.info("Connected to Neo4j at %s", connection.uri)

    def close(self) -> None:
        self._driver.close()
        logger.info("Neo4j connection closed")

    def __enter__(self) -> "Neo4jWriter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- Hooks ---------------------------------------------------------------

    def run_hooks(self, hooks: list[SchemaHook]) -> None:
        """Execute a list of Cypher hooks (indexes, constraints, etc.)."""
        if not hooks:
            return
        with self._driver.session(database=self._connection.database) as session:
            for hook in hooks:
                desc = hook.description or hook.cypher[:60]
                logger.info("Running hook: %s", desc)
                session.run(hook.cypher)

    # -- Schema enforcement --------------------------------------------------

    def apply_schema(self, schema: SchemaDefinition) -> None:
        """Generate and execute Cypher for constraints and indexes."""
        hooks = schema.to_hooks()
        if hooks:
            logger.info(
                "Applying schema: %d constraints, %d indexes",
                len(schema.constraints),
                len(schema.indexes),
            )
            self.run_hooks(hooks)

    # -- Node writing --------------------------------------------------------

    @staticmethod
    def _build_node_query(mapping: NodeMapping) -> str:
        """Build a parameterised Cypher MERGE query for nodes."""
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
        """Extract and transform the fields needed for a single node."""
        row: Record = {}
        for prop in mapping.properties:
            value = record.get(prop.source_field)
            value = apply_transforms(value, _extract_transform_config(prop))
            row[prop.target_name] = value
        # Ensure the key field is always present
        if mapping.key not in row:
            key_field = next(
                (p.source_field for p in mapping.properties if p.target_name == mapping.key),
                mapping.key,
            )
            row[mapping.key] = record.get(key_field)

        # ID generation: compute a deterministic ID from natural key fields
        if mapping.id_generation:
            id_gen = IdGenerationConfig(**mapping.id_generation.model_dump())
            row[mapping.key] = id_gen.generate_id(record)

        return row

    def _run_batch(self, query: str, batch: list[Record]) -> None:
        """Execute a single batch with retry on transient errors."""
        def _execute() -> None:
            with self._driver.session(database=self._connection.database) as session:
                session.run(query, rows=batch)

        retry(
            _execute,
            max_attempts=self._retry_max_attempts,
            base_delay=self._retry_base_delay,
            retryable_exceptions=_RETRYABLE,
        )

    def write_nodes(
        self,
        records: list[Record],
        mapping: NodeMapping,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> int:
        """Write nodes to Neo4j in batches with transforms and retry."""
        query = self._build_node_query(mapping)
        rows = [self._map_node_row(r, mapping) for r in records]
        total = 0

        progress = ProgressReporter(
            total=len(rows),
            step_name=f"nodes:{mapping.label}",
            report_every=max(batch_size, 1000),
        )

        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            self._run_batch(query, batch)
            total += len(batch)
            progress.advance(len(batch))

        logger.info("Created/merged %d %s nodes", total, mapping.label)
        return total

    # -- Relationship writing ------------------------------------------------

    @staticmethod
    def _build_rel_query(mapping: RelationshipMapping) -> str:
        """Build a parameterised Cypher MERGE query for relationships."""
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
    def _map_rel_row(record: Record, mapping: RelationshipMapping) -> Record:
        """Extract and transform the fields needed for a single relationship."""
        row: Record = {
            "from_val": record.get(mapping.from_field),
            "to_val": record.get(mapping.to_field),
        }
        for prop in mapping.properties:
            value = record.get(prop.source_field)
            value = apply_transforms(value, _extract_transform_config(prop))
            row[prop.target_name] = value
        return row

    def write_relationships(
        self,
        records: list[Record],
        mapping: RelationshipMapping,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> int:
        """Write relationships to Neo4j in batches with transforms and retry."""
        query = self._build_rel_query(mapping)
        rows = [self._map_rel_row(r, mapping) for r in records]
        total = 0

        progress = ProgressReporter(
            total=len(rows),
            step_name=f"rels:{mapping.rel_type}",
            report_every=max(batch_size, 1000),
        )

        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            self._run_batch(query, batch)
            total += len(batch)
            progress.advance(len(batch))

        logger.info("Created/merged %d %s relationships", total, mapping.rel_type)
        return total
