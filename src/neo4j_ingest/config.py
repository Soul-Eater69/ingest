"""Configuration models for the ingestion framework.

Config files (YAML or JSON) define:
- Neo4j connection details
- Data sources (CSV, JSON, SQL, REST API)
- Node mappings (which source fields become node properties)
- Relationship mappings (how nodes connect to each other)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class Neo4jConnection(BaseModel):
    """Neo4j database connection settings."""

    uri: str = "bolt://localhost:7687"
    username: str = "neo4j"
    password: str = "neo4j"
    database: str = "neo4j"


class SourceConfig(BaseModel):
    """A data source definition.

    Supported types:
    - csv: read from a CSV file (path required)
    - json: read from a JSON file (path required, json_root optional)
    - sql: read from a SQL database (connection_string + query required)
    - rest: read from a REST API (url required, headers/params/json_root optional)
    """

    name: str
    type: Literal["csv", "json", "sql", "rest"]

    # File-based sources
    path: str | None = None

    # SQL source
    connection_string: str | None = None
    query: str | None = None

    # REST source
    url: str | None = None
    method: str = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    params: dict[str, str] = Field(default_factory=dict)
    body: dict[str, Any] | None = None

    # JSON / REST: dotted path to the array of records (e.g. "data.items")
    json_root: str | None = None

    @model_validator(mode="after")
    def check_required_fields(self) -> "SourceConfig":
        if self.type == "csv" and not self.path:
            raise ValueError("CSV source requires 'path'")
        if self.type == "json" and not self.path:
            raise ValueError("JSON source requires 'path'")
        if self.type == "sql" and (not self.connection_string or not self.query):
            raise ValueError("SQL source requires 'connection_string' and 'query'")
        if self.type == "rest" and not self.url:
            raise ValueError("REST source requires 'url'")
        return self


class PropertyMapping(BaseModel):
    """Maps a source field to a Neo4j property.

    If `target` is omitted the source field name is used as-is.
    """

    source_field: str
    target: str | None = None

    @property
    def target_name(self) -> str:
        return self.target or self.source_field


class NodeMapping(BaseModel):
    """Defines how source records become Neo4j nodes.

    Attributes:
        source: name of the source (must match a SourceConfig.name)
        label: Neo4j node label
        key: property used to MERGE (deduplicate) nodes
        properties: list of field-to-property mappings
    """

    source: str
    label: str
    key: str
    properties: list[PropertyMapping]


class RelationshipMapping(BaseModel):
    """Defines how to create relationships between nodes.

    Attributes:
        source: name of the data source providing the records
        rel_type: Neo4j relationship type (e.g. "WORKS_AT")
        from_label: label of the start node
        from_key: property on the start node used for matching
        from_field: source field whose value matches from_key
        to_label: label of the end node
        to_key: property on the end node used for matching
        to_field: source field whose value matches to_key
        properties: optional properties to set on the relationship
    """

    source: str
    rel_type: str
    from_label: str
    from_key: str
    from_field: str
    to_label: str
    to_key: str
    to_field: str
    properties: list[PropertyMapping] = Field(default_factory=list)


class IngestConfig(BaseModel):
    """Top-level configuration for an ingestion job."""

    neo4j: Neo4jConnection = Field(default_factory=Neo4jConnection)
    sources: list[SourceConfig]
    nodes: list[NodeMapping]
    relationships: list[RelationshipMapping] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> "IngestConfig":
        source_names = {s.name for s in self.sources}
        for node in self.nodes:
            if node.source not in source_names:
                raise ValueError(
                    f"Node mapping references unknown source '{node.source}'"
                )
        for rel in self.relationships:
            if rel.source not in source_names:
                raise ValueError(
                    f"Relationship mapping references unknown source '{rel.source}'"
                )
        return self


def load_config(path: str | Path) -> IngestConfig:
    """Load and validate a config file (YAML or JSON)."""
    path = Path(path)
    text = path.read_text()

    if path.suffix in (".yaml", ".yml"):
        raw = yaml.safe_load(text)
    elif path.suffix == ".json":
        raw = json.loads(text)
    else:
        # Try YAML first, fall back to JSON
        try:
            raw = yaml.safe_load(text)
        except yaml.YAMLError:
            raw = json.loads(text)

    return IngestConfig.model_validate(raw)
