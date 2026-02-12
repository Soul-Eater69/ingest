"""Configuration models for the ingestion framework.

Config files (YAML or JSON) define:
- Neo4j connection details (with env var substitution for secrets)
- Data sources (CSV, JSON, SQL, REST API — extensible via plugins)
- Node mappings with per-field transforms and validation
- Relationship mappings
- Schema hooks (pre/post Cypher queries for indexes/constraints)
- Job-level settings (batch size, error strategy, rate limits)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from neo4j_ingest.env import resolve_env_vars


# ---------------------------------------------------------------------------
# Neo4j connection
# ---------------------------------------------------------------------------

class Neo4jConnection(BaseModel):
    """Neo4j database connection settings."""

    uri: str = "bolt://localhost:7687"
    username: str = "neo4j"
    password: str = "neo4j"
    database: str = "neo4j"
    max_connection_pool_size: int = 100
    connection_acquisition_timeout: float = 60.0
    encrypted: bool = False


# ---------------------------------------------------------------------------
# Source configuration
# ---------------------------------------------------------------------------

class RateLimitConfig(BaseModel):
    """Rate limiting for REST sources."""

    requests_per_second: float = 10.0
    burst: int = 1


class PaginationConfig(BaseModel):
    """Pagination settings for REST sources."""

    type: Literal["offset", "cursor", "page"] = "offset"
    page_param: str = "page"
    page_size_param: str = "per_page"
    page_size: int = 100
    max_pages: int = 1000
    # For cursor-based pagination
    cursor_field: str | None = None
    next_cursor_path: str | None = None


class SourceConfig(BaseModel):
    """A data source definition.

    Supported built-in types: csv, json, sql, rest.
    Custom types can be registered via the plugin registry.
    """

    name: str
    type: str  # Not restricted to Literal — allows plugin types

    # File-based sources
    path: str | None = None
    encoding: str = "utf-8"
    delimiter: str = ","

    # SQL source
    connection_string: str | None = None
    query: str | None = None
    chunk_size: int | None = None  # For chunked SQL reads

    # REST source
    url: str | None = None
    method: str = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    params: dict[str, str] = Field(default_factory=dict)
    body: dict[str, Any] | None = None
    timeout: float = 60.0
    rate_limit: RateLimitConfig | None = None
    pagination: PaginationConfig | None = None

    # JSON / REST: dotted path to the array of records
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


# ---------------------------------------------------------------------------
# Transform configuration
# ---------------------------------------------------------------------------

class TransformConfig(BaseModel):
    """A single transform step applied to a field value."""

    type: str
    params: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Validation configuration
# ---------------------------------------------------------------------------

class ValidationRuleConfig(BaseModel):
    """A single validation rule for a source field."""

    field: str
    rule: str  # required, type, regex, min, max, one_of
    params: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None


class ValidationConfig(BaseModel):
    """Validation settings for a node or relationship mapping."""

    rules: list[ValidationRuleConfig] = Field(default_factory=list)
    on_error: Literal["skip", "fail", "dead_letter"] = "skip"


# ---------------------------------------------------------------------------
# Property and node/relationship mappings
# ---------------------------------------------------------------------------

class PropertyMapping(BaseModel):
    """Maps a source field to a Neo4j property, with optional transforms."""

    source_field: str
    target: str | None = None
    transform: list[TransformConfig] | TransformConfig | None = None

    @property
    def target_name(self) -> str:
        return self.target or self.source_field


class NodeMapping(BaseModel):
    """Defines how source records become Neo4j nodes."""

    source: str
    label: str
    key: str
    properties: list[PropertyMapping]
    validation: ValidationConfig | None = None


class RelationshipMapping(BaseModel):
    """Defines how to create relationships between nodes."""

    source: str
    rel_type: str
    from_label: str
    from_key: str
    from_field: str
    to_label: str
    to_key: str
    to_field: str
    properties: list[PropertyMapping] = Field(default_factory=list)
    validation: ValidationConfig | None = None


# ---------------------------------------------------------------------------
# Schema hooks
# ---------------------------------------------------------------------------

class SchemaHook(BaseModel):
    """A Cypher query to run before or after ingestion.

    Used for creating indexes, constraints, or any setup/teardown logic.
    """

    cypher: str
    description: str = ""


# ---------------------------------------------------------------------------
# Job-level settings
# ---------------------------------------------------------------------------

class JobSettings(BaseModel):
    """Global job-level configuration."""

    batch_size: int = 500
    parallel_sources: bool = False
    max_workers: int = 4
    health_check: bool = True
    retry_max_attempts: int = 3
    retry_base_delay: float = 1.0
    continue_on_source_error: bool = False
    metrics_output: str | None = None  # Path to write JSON metrics


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------

class IngestConfig(BaseModel):
    """Top-level configuration for an ingestion job."""

    neo4j: Neo4jConnection = Field(default_factory=Neo4jConnection)
    settings: JobSettings = Field(default_factory=JobSettings)
    sources: list[SourceConfig]
    nodes: list[NodeMapping]
    relationships: list[RelationshipMapping] = Field(default_factory=list)
    pre_hooks: list[SchemaHook] = Field(default_factory=list)
    post_hooks: list[SchemaHook] = Field(default_factory=list)

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


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(path: str | Path) -> IngestConfig:
    """Load, resolve env vars, and validate a config file (YAML or JSON)."""
    path = Path(path)
    text = path.read_text()

    if path.suffix in (".yaml", ".yml"):
        raw = yaml.safe_load(text)
    elif path.suffix == ".json":
        raw = json.loads(text)
    else:
        try:
            raw = yaml.safe_load(text)
        except yaml.YAMLError:
            raw = json.loads(text)

    # Resolve ${ENV_VAR} and ${ENV_VAR:-default} patterns
    raw = resolve_env_vars(raw)

    return IngestConfig.model_validate(raw)
