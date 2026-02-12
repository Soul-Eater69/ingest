"""Ingestion engine — the orchestrator.

Reads the config, fetches data from each source, and writes nodes and
relationships to Neo4j according to the mappings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from neo4j_ingest.config import IngestConfig, load_config
from neo4j_ingest.graph import Neo4jWriter
from neo4j_ingest.sources import read_source

logger = logging.getLogger(__name__)

Record = dict[str, Any]


@dataclass
class IngestResult:
    """Summary of an ingestion run."""

    nodes_created: dict[str, int] = field(default_factory=dict)
    relationships_created: dict[str, int] = field(default_factory=dict)

    @property
    def total_nodes(self) -> int:
        return sum(self.nodes_created.values())

    @property
    def total_relationships(self) -> int:
        return sum(self.relationships_created.values())


def run(config: IngestConfig, batch_size: int = 500) -> IngestResult:
    """Execute the full ingestion pipeline.

    1. Read data from every declared source.
    2. For each node mapping, create/merge nodes.
    3. For each relationship mapping, create/merge relationships.
    """
    result = IngestResult()

    # Step 1 — read all sources into memory keyed by name
    source_data: dict[str, list[Record]] = {}
    for source_cfg in config.sources:
        source_data[source_cfg.name] = read_source(source_cfg)

    # Step 2 & 3 — write to Neo4j
    with Neo4jWriter(config.neo4j) as writer:
        # Nodes first (relationships depend on nodes existing)
        for node_mapping in config.nodes:
            records = source_data[node_mapping.source]
            count = writer.write_nodes(records, node_mapping, batch_size=batch_size)
            result.nodes_created[node_mapping.label] = (
                result.nodes_created.get(node_mapping.label, 0) + count
            )

        # Then relationships
        for rel_mapping in config.relationships:
            records = source_data[rel_mapping.source]
            count = writer.write_relationships(
                records, rel_mapping, batch_size=batch_size
            )
            result.relationships_created[rel_mapping.rel_type] = (
                result.relationships_created.get(rel_mapping.rel_type, 0) + count
            )

    logger.info(
        "Ingestion complete: %d nodes, %d relationships",
        result.total_nodes,
        result.total_relationships,
    )
    return result


def run_from_file(config_path: str, batch_size: int = 500) -> IngestResult:
    """Load a config file and run the ingestion pipeline."""
    config = load_config(config_path)
    return run(config, batch_size=batch_size)
