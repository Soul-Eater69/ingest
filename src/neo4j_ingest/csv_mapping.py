"""CSV mapping loader.

Parses a CSV mapping file (spreadsheet-style) into IngestConfig components.
Each row maps a source column to a Neo4j target, with cardinality indicating
whether the mapping is a node property (1:1) or a relationship (1:M / M:1).

Expected CSV columns:
    source_entity       – source name (matches a SourceConfig.name)
    field_cardinality   – "1:1" for properties, "1:M" or "M:1" for relationships
    source_column       – field name in the source data
    data_type           – target data type (string, int, float, bool, datetime)
    is_key              – "true" if this field is the merge key
    transform           – optional transform name (e.g. "strip", "lowercase")
    target_entity       – Neo4j node label
    target_column       – Neo4j property name
    relationship_type   – relationship type for 1:M / M:1 rows
    rel_source_key      – source-side key for the relationship
    rel_target_key      – target-side key for the relationship

Rows with cardinality 1:1 become property mappings on nodes.
Rows with cardinality 1:M or M:1 define relationships between entities.
"""

from __future__ import annotations

import csv
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from neo4j_ingest.config import (
    IngestConfig,
    Neo4jConnection,
    NodeMapping,
    PropertyMapping,
    RelationshipMapping,
    SchemaConstraint,
    SchemaDefinition,
    SchemaIndex,
    SourceConfig,
    TransformConfig,
)

logger = logging.getLogger(__name__)

# Maps CSV data_type values to transform types
_TYPE_TRANSFORMS: dict[str, str] = {
    "int": "to_int",
    "integer": "to_int",
    "float": "to_float",
    "bool": "to_bool",
    "boolean": "to_bool",
    "datetime": "to_datetime",
    "date": "to_datetime",
}


def _normalise_row(row: dict[str, str]) -> dict[str, str]:
    """Normalise CSV column names to lowercase/underscored keys."""
    return {k.strip().lower().replace(" ", "_"): v.strip() for k, v in row.items()}


def _build_transforms(row: dict[str, str]) -> list[TransformConfig] | None:
    """Build a transform chain from data_type and transform columns."""
    transforms: list[TransformConfig] = []

    data_type = row.get("data_type", "").lower()
    if data_type in _TYPE_TRANSFORMS:
        transforms.append(TransformConfig(type=_TYPE_TRANSFORMS[data_type]))

    transform_name = row.get("transform", "").strip()
    if transform_name:
        for t in transform_name.split(","):
            t = t.strip()
            if t:
                transforms.append(TransformConfig(type=t))

    return transforms if transforms else None


def _is_truthy(value: str) -> bool:
    return value.strip().lower() in ("true", "yes", "1", "x")


def load_csv_mapping(
    path: str | Path,
    *,
    sources: list[dict[str, Any]] | None = None,
    neo4j: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
    auto_schema: bool = True,
) -> IngestConfig:
    """Load a CSV mapping file and build an IngestConfig.

    Parameters
    ----------
    path
        Path to the CSV mapping file.
    sources
        Optional list of source config dicts.  If not provided, stub CSV
        sources are generated for each unique ``source_entity``.
    neo4j
        Optional Neo4j connection overrides.
    settings
        Optional job settings overrides.
    auto_schema
        If True, automatically generate uniqueness constraints for key fields.

    Returns
    -------
    IngestConfig
        A fully validated configuration ready for the engine.
    """
    path = Path(path)
    logger.info("Loading CSV mapping from %s", path)

    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = [_normalise_row(r) for r in reader]

    logger.info("Parsed %d mapping rows", len(rows))

    # Collect node properties and relationships per source entity
    # Structure: {source_entity: {target_entity: {"key": ..., "properties": [...]}}}
    node_map: dict[str, dict[str, dict[str, Any]]] = defaultdict(
        lambda: defaultdict(lambda: {"key": None, "properties": []})
    )
    relationships: list[RelationshipMapping] = []
    key_fields: list[tuple[str, str]] = []  # (label, property) for schema generation
    source_entities: set[str] = set()

    for row in rows:
        source_entity = row.get("source_entity", "").strip()
        cardinality = row.get("field_cardinality", "1:1").strip()
        source_column = row.get("source_column", "").strip()
        target_entity = row.get("target_entity", "").strip()
        target_column = row.get("target_column", "").strip() or source_column
        is_key = _is_truthy(row.get("is_key", ""))

        if not source_entity or not source_column:
            logger.warning("Skipping row with empty source_entity or source_column")
            continue

        source_entities.add(source_entity)
        transforms = _build_transforms(row)

        if cardinality == "1:1":
            # Node property
            target = target_entity or source_entity
            prop = PropertyMapping(
                source_field=source_column,
                target=target_column if target_column != source_column else None,
                transform=transforms,
            )
            entry = node_map[source_entity][target]
            entry["properties"].append(prop)

            if is_key:
                entry["key"] = target_column or source_column
                key_fields.append((target, target_column or source_column))

        elif cardinality in ("1:M", "M:1", "1:m", "m:1"):
            # Relationship definition
            rel_type = row.get("relationship_type", "").strip()
            rel_source_key = row.get("rel_source_key", "").strip() or source_column
            rel_target_key = row.get("rel_target_key", "").strip() or target_column

            if not rel_type:
                # Auto-generate relationship type from entities
                from_ent = source_entity.upper()
                to_ent = target_entity.upper()
                rel_type = f"HAS_{to_ent}" if cardinality in ("1:M", "1:m") else f"BELONGS_TO_{from_ent}"

            if not target_entity:
                logger.warning(
                    "Skipping relationship row: no target_entity for source_column '%s'",
                    source_column,
                )
                continue

            # Determine direction based on cardinality
            if cardinality in ("1:M", "1:m"):
                from_label = source_entity
                from_key = rel_source_key
                from_field = source_column
                to_label = target_entity
                to_key = rel_target_key
                to_field = source_column
            else:  # M:1
                from_label = source_entity
                from_key = rel_source_key
                from_field = source_column
                to_label = target_entity
                to_key = rel_target_key
                to_field = source_column

            rel = RelationshipMapping(
                source=source_entity,
                rel_type=rel_type,
                from_label=from_label,
                from_key=from_key,
                from_field=source_column,
                to_label=to_label,
                to_key=rel_target_key,
                to_field=source_column,
            )
            relationships.append(rel)

    # Build NodeMappings
    nodes: list[NodeMapping] = []
    for source_entity, targets in node_map.items():
        for target_label, info in targets.items():
            key = info["key"]
            if not key and info["properties"]:
                # Default: use first property as key
                key = info["properties"][0].target_name
                logger.warning(
                    "No key defined for %s -> %s, defaulting to '%s'",
                    source_entity,
                    target_label,
                    key,
                )
            nodes.append(
                NodeMapping(
                    source=source_entity,
                    label=target_label,
                    key=key,
                    properties=info["properties"],
                )
            )

    # Build stub SourceConfigs if not provided
    if sources:
        source_configs = [SourceConfig.model_validate(s) for s in sources]
    else:
        source_configs = [
            SourceConfig(name=name, type="csv", path=f"{name}.csv")
            for name in sorted(source_entities)
        ]
        logger.info(
            "Auto-generated %d stub source configs (update paths before running)",
            len(source_configs),
        )

    # Build schema if auto_schema is enabled
    schema = None
    if auto_schema and key_fields:
        constraints = [
            SchemaConstraint(label=label, property=prop, type="unique")
            for label, prop in key_fields
        ]
        schema = SchemaDefinition(constraints=constraints)
        logger.info("Auto-generated %d schema constraints from key fields", len(constraints))

    return IngestConfig(
        neo4j=Neo4jConnection(**(neo4j or {})),
        settings=settings or {},
        sources=source_configs,
        nodes=nodes,
        relationships=relationships,
        graph_schema=schema,
    )
