"""Knowledge Graph mapping schema loader.

Parses a JSON KG mapping schema (like the ``kg-mapping-schema.json`` format)
into the framework's IngestConfig.  This schema format is richer than YAML
configs — it supports:

- **Versioned metadata** with changelogs
- **Source definitions** — named data sources with format/example metadata
- **ID generation** — SHA-256 hashing of natural keys for deterministic,
  reproducible, collision-free node IDs
- **Per-property source tracking** — every property declares which source
  it came from
- **Node definitions** with natural keys and typed properties
- **Relationship definitions** with source/target labels and properties

JSON schema structure::

    {
      "$id": "kg-mapping-schema.json",
      "title": "...",
      "version": "4.0.0",
      "metadata": { ... },
      "idGeneration": {
        "strategy": "sha256-hash",
        "hashLength": 16,
        ...
      },
      "sourceDefinitions": {
        "codeql": { "description": "...", "dataFormat": "...", "examples": [...] },
        ...
      },
      "nodes": [
        {
          "label": "Method",
          "naturalKey": ["repo", "class_name", "method_name"],
          "idField": "_id",
          "source": "codeql",
          "properties": {
            "name": {
              "source": "codeql",
              "sourceField": "method_name",
              "type": "string",
              "required": true,
              "description": "..."
            },
            ...
          }
        }
      ],
      "relationships": [
        {
          "type": "HAS_METHOD",
          "source": "codeql",
          "fromNode": "Class",
          "fromKey": "_id",
          "fromField": "class_id",
          "toNode": "Method",
          "toKey": "_id",
          "toField": "method_id",
          "properties": { ... }
        }
      ]
    }
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from neo4j_ingest.config import (
    IdGenerationConfig,
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

# Maps JSON type names → framework transform types
_TYPE_TRANSFORMS: dict[str, str] = {
    "int": "to_int",
    "integer": "to_int",
    "float": "to_float",
    "number": "to_float",
    "bool": "to_bool",
    "boolean": "to_bool",
    "datetime": "to_datetime",
    "date": "to_datetime",
}


def _build_property_transforms(
    prop_def: dict[str, Any],
) -> list[TransformConfig] | None:
    """Build transforms from a KG property definition."""
    transforms: list[TransformConfig] = []

    # Type coercion
    prop_type = prop_def.get("type", "string").lower()
    if prop_type in _TYPE_TRANSFORMS:
        transforms.append(TransformConfig(type=_TYPE_TRANSFORMS[prop_type]))

    # Explicit transforms if specified
    for t in prop_def.get("transforms", []):
        if isinstance(t, str):
            transforms.append(TransformConfig(type=t))
        elif isinstance(t, dict):
            transforms.append(
                TransformConfig(type=t["type"], params=t.get("params", {}))
            )

    return transforms if transforms else None


def _parse_id_generation(raw: dict[str, Any]) -> IdGenerationConfig:
    """Parse the top-level idGeneration block."""
    strategy = raw.get("strategy", "sha256-hash")
    return IdGenerationConfig(
        strategy=strategy,
        hash_length=raw.get("hashLength", raw.get("hash_length", 16)),
        separator=raw.get("separator", ":"),
        prefix=raw.get("prefix", ""),
    )


def _parse_node(
    node_def: dict[str, Any],
    default_id_gen: IdGenerationConfig | None,
    default_source: str | None,
) -> tuple[NodeMapping, list[tuple[str, str]]]:
    """Parse a single node definition.

    Returns (NodeMapping, list of (label, key_property) for schema generation).
    """
    label = node_def["label"]
    natural_key: list[str] = node_def.get("naturalKey", [])
    id_field = node_def.get("idField", "_id")
    source_name = node_def.get("source", default_source or "default")

    # Build property mappings from the properties dict
    properties: list[PropertyMapping] = []
    prop_defs: dict[str, Any] = node_def.get("properties", {})

    for target_name, prop_def in prop_defs.items():
        if isinstance(prop_def, str):
            # Short form: "target": "source_field"
            prop_def = {"sourceField": prop_def}

        source_field = prop_def.get("sourceField", prop_def.get("source_field", target_name))
        transforms = _build_property_transforms(prop_def)

        properties.append(
            PropertyMapping(
                source_field=source_field,
                target=target_name if target_name != source_field else None,
                transform=transforms,
            )
        )

    # Build ID generation config for this node
    id_gen = None
    if natural_key:
        # Node has natural keys → use ID generation
        node_id_gen_raw = node_def.get("idGeneration", {})
        if node_id_gen_raw:
            id_gen = _parse_id_generation(node_id_gen_raw)
            id_gen.fields = natural_key
        elif default_id_gen:
            id_gen = default_id_gen.model_copy()
            id_gen.fields = natural_key
        else:
            id_gen = IdGenerationConfig(
                strategy="sha256-hash",
                fields=natural_key,
                hash_length=16,
            )

    # Determine the merge key
    key = id_field if natural_key else _pick_key(properties, node_def)

    key_fields: list[tuple[str, str]] = [(label, key)]

    return (
        NodeMapping(
            source=source_name,
            label=label,
            key=key,
            properties=properties,
            id_generation=id_gen,
        ),
        key_fields,
    )


def _pick_key(properties: list[PropertyMapping], node_def: dict[str, Any]) -> str:
    """Pick the merge key from explicit config or first required property."""
    # Explicit key field
    if "key" in node_def:
        return node_def["key"]

    # Look for a property marked required
    prop_defs = node_def.get("properties", {})
    for name, pdef in prop_defs.items():
        if isinstance(pdef, dict) and pdef.get("required"):
            return name

    # Fall back to first property
    if properties:
        return properties[0].target_name

    return "id"


def _parse_relationship(
    rel_def: dict[str, Any],
    default_source: str | None,
) -> RelationshipMapping:
    """Parse a single relationship definition."""
    source_name = rel_def.get("source", default_source or "default")
    rel_type = rel_def["type"]
    from_node = rel_def.get("fromNode", rel_def.get("from_label", ""))
    to_node = rel_def.get("toNode", rel_def.get("to_label", ""))
    from_key = rel_def.get("fromKey", rel_def.get("from_key", "_id"))
    to_key = rel_def.get("toKey", rel_def.get("to_key", "_id"))
    from_field = rel_def.get("fromField", rel_def.get("from_field", from_key))
    to_field = rel_def.get("toField", rel_def.get("to_field", to_key))

    # Parse relationship properties
    properties: list[PropertyMapping] = []
    prop_defs: dict[str, Any] = rel_def.get("properties", {})
    for target_name, prop_def in prop_defs.items():
        if isinstance(prop_def, str):
            prop_def = {"sourceField": prop_def}
        source_field = prop_def.get("sourceField", prop_def.get("source_field", target_name))
        transforms = _build_property_transforms(prop_def)
        properties.append(
            PropertyMapping(
                source_field=source_field,
                target=target_name if target_name != source_field else None,
                transform=transforms,
            )
        )

    return RelationshipMapping(
        source=source_name,
        rel_type=rel_type,
        from_label=from_node,
        from_key=from_key,
        from_field=from_field,
        to_label=to_node,
        to_key=to_key,
        to_field=to_field,
        properties=properties,
    )


def is_kg_mapping_schema(data: dict[str, Any]) -> bool:
    """Detect whether a parsed JSON dict is a KG mapping schema.

    Heuristic: the document has a ``nodes`` key that is a list of dicts
    with ``label`` and ``properties`` keys, or has explicit markers like
    ``$id``, ``idGeneration``, or ``sourceDefinitions``.
    """
    if any(k in data for k in ("$id", "idGeneration", "sourceDefinitions")):
        return True
    nodes = data.get("nodes")
    if isinstance(nodes, list) and nodes:
        first = nodes[0]
        if isinstance(first, dict) and "label" in first and "properties" in first:
            # Check properties is a dict (KG style) not a list (IngestConfig style)
            if isinstance(first["properties"], dict):
                return True
    return False


def load_kg_schema(
    path: str | Path,
    *,
    sources: list[dict[str, Any]] | None = None,
    neo4j: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> IngestConfig:
    """Load a KG mapping schema JSON and build an IngestConfig.

    Parameters
    ----------
    path
        Path to the JSON KG mapping schema file.
    sources
        Optional list of source config dicts. If not provided, stub
        sources are generated from the schema's sourceDefinitions.
    neo4j
        Optional Neo4j connection overrides.
    settings
        Optional job settings overrides.
    """
    path = Path(path)
    logger.info("Loading KG mapping schema from %s", path)

    raw = json.loads(path.read_text())
    return load_kg_schema_from_dict(
        raw,
        sources=sources,
        neo4j=neo4j,
        settings=settings,
    )


def load_kg_schema_from_dict(
    raw: dict[str, Any],
    *,
    sources: list[dict[str, Any]] | None = None,
    neo4j: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> IngestConfig:
    """Build an IngestConfig from a parsed KG mapping schema dict."""

    version = raw.get("version", "unknown")
    title = raw.get("title", "Untitled KG Schema")
    logger.info("KG mapping schema: %s v%s", title, version)

    # Parse global ID generation
    default_id_gen = None
    id_gen_raw = raw.get("idGeneration")
    if id_gen_raw:
        default_id_gen = _parse_id_generation(id_gen_raw)

    # Parse source definitions
    source_defs: dict[str, Any] = raw.get("sourceDefinitions", {})
    all_source_names: set[str] = set(source_defs.keys())

    # Find the default source (first defined, or None)
    default_source = next(iter(source_defs), None)

    # Parse nodes
    node_mappings: list[NodeMapping] = []
    key_fields: list[tuple[str, str]] = []

    for node_def in raw.get("nodes", []):
        mapping, keys = _parse_node(node_def, default_id_gen, default_source)
        node_mappings.append(mapping)
        key_fields.extend(keys)
        all_source_names.add(mapping.source)

    # Parse relationships
    rel_mappings: list[RelationshipMapping] = []
    for rel_def in raw.get("relationships", []):
        mapping = _parse_relationship(rel_def, default_source)
        rel_mappings.append(mapping)
        all_source_names.add(mapping.source)

    # Build source configs
    if sources:
        source_configs = [SourceConfig.model_validate(s) for s in sources]
    else:
        source_configs = []
        for name in sorted(all_source_names):
            sdef = source_defs.get(name, {})
            data_format = sdef.get("dataFormat", "").lower()

            # Infer type from dataFormat
            if "csv" in data_format:
                src_type = "csv"
            elif "json" in data_format:
                src_type = "json"
            elif "sql" in data_format:
                src_type = "sql"
            else:
                src_type = "json"  # default for JSONL/unknown

            # Get example path if available
            examples = sdef.get("examples", [])
            example_path = examples[0] if examples else f"{name}_data.json"

            source_configs.append(
                SourceConfig(name=name, type=src_type, path=example_path)
            )

        logger.info(
            "Auto-generated %d source configs from sourceDefinitions",
            len(source_configs),
        )

    # Build schema (constraints + indexes for key fields)
    constraints = [
        SchemaConstraint(label=label, property=prop, type="unique")
        for label, prop in key_fields
    ]
    indexes = [
        SchemaIndex(label=label, properties=[prop], type="range")
        for label, prop in key_fields
    ]
    graph_schema = SchemaDefinition(constraints=constraints, indexes=indexes)

    return IngestConfig(
        neo4j=Neo4jConnection(**(neo4j or {})),
        settings=settings or {},
        sources=source_configs,
        nodes=node_mappings,
        relationships=rel_mappings,
        graph_schema=graph_schema,
    )
