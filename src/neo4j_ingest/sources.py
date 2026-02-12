"""Data source connectors.

Each connector reads from a source type and yields a list of dictionaries
(records) that the ingestion engine can map to Neo4j nodes/relationships.
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

import requests
import sqlalchemy

from neo4j_ingest.config import SourceConfig

logger = logging.getLogger(__name__)

Record = dict[str, Any]


def _resolve_json_root(data: Any, json_root: str | None) -> list[Record]:
    """Walk a dotted path (e.g. 'data.items') into a nested structure."""
    if json_root is None:
        if isinstance(data, list):
            return data
        raise ValueError(
            "JSON data is not a list; specify 'json_root' to point to the array"
        )
    for part in json_root.split("."):
        if isinstance(data, dict):
            data = data[part]
        elif isinstance(data, list):
            data = data[int(part)]
        else:
            raise ValueError(f"Cannot traverse into {type(data)} with key '{part}'")
    if not isinstance(data, list):
        raise ValueError(f"json_root '{json_root}' did not resolve to a list")
    return data


def read_csv(config: SourceConfig) -> list[Record]:
    """Read records from a CSV file."""
    path = Path(config.path)  # type: ignore[arg-type]
    logger.info("Reading CSV source '%s' from %s", config.name, path)
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        records = list(reader)
    logger.info("Read %d records from CSV '%s'", len(records), config.name)
    return records


def read_json(config: SourceConfig) -> list[Record]:
    """Read records from a JSON file."""
    path = Path(config.path)  # type: ignore[arg-type]
    logger.info("Reading JSON source '%s' from %s", config.name, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    records = _resolve_json_root(data, config.json_root)
    logger.info("Read %d records from JSON '%s'", len(records), config.name)
    return records


def read_sql(config: SourceConfig) -> list[Record]:
    """Read records from a SQL database using SQLAlchemy."""
    logger.info("Reading SQL source '%s'", config.name)
    engine = sqlalchemy.create_engine(config.connection_string)  # type: ignore[arg-type]
    with engine.connect() as conn:
        result = conn.execute(sqlalchemy.text(config.query))  # type: ignore[arg-type]
        columns = list(result.keys())
        records = [dict(zip(columns, row)) for row in result.fetchall()]
    logger.info("Read %d records from SQL '%s'", len(records), config.name)
    return records


def read_rest(config: SourceConfig) -> list[Record]:
    """Read records from a REST API endpoint."""
    logger.info("Reading REST source '%s' from %s", config.name, config.url)
    response = requests.request(
        method=config.method,
        url=config.url,  # type: ignore[arg-type]
        headers=config.headers or None,
        params=config.params or None,
        json=config.body,
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    records = _resolve_json_root(data, config.json_root)
    logger.info("Read %d records from REST '%s'", len(records), config.name)
    return records


# Dispatcher -----------------------------------------------------------------

_READERS = {
    "csv": read_csv,
    "json": read_json,
    "sql": read_sql,
    "rest": read_rest,
}


def read_source(config: SourceConfig) -> list[Record]:
    """Read records from a source based on its type."""
    reader = _READERS.get(config.type)
    if reader is None:
        raise ValueError(f"Unsupported source type: {config.type}")
    return reader(config)
