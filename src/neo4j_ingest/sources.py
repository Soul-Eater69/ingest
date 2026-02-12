"""Data source connectors.

Each connector reads from a source type and returns a list of dictionaries.
Features:
- Streaming/chunked reads for large datasets
- Rate limiting for REST APIs
- Pagination support for REST APIs
- Plugin registry for custom source types
- Configurable encoding and delimiters
"""

from __future__ import annotations

import csv
import json
import logging
import time
from pathlib import Path
from typing import Any

import requests
import sqlalchemy

from neo4j_ingest.config import SourceConfig
from neo4j_ingest.registry import source_registry

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


class RateLimiter:
    """Token-bucket rate limiter."""

    def __init__(self, requests_per_second: float = 10.0, burst: int = 1) -> None:
        self._rate = requests_per_second
        self._burst = burst
        self._tokens = float(burst)
        self._last_time = time.monotonic()

    def acquire(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_time
        self._last_time = now
        self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
        if self._tokens < 1.0:
            wait = (1.0 - self._tokens) / self._rate
            logger.debug("Rate limiter: sleeping %.2fs", wait)
            time.sleep(wait)
            self._tokens = 0.0
        else:
            self._tokens -= 1.0


# ---------------------------------------------------------------------------
# Built-in readers (auto-registered via decorator)
# ---------------------------------------------------------------------------

@source_registry.register("csv")
def read_csv(config: SourceConfig) -> list[Record]:
    """Read records from a CSV file with configurable encoding and delimiter."""
    path = Path(config.path)  # type: ignore[arg-type]
    logger.info("Reading CSV source '%s' from %s", config.name, path)
    with path.open(newline="", encoding=config.encoding) as fh:
        reader = csv.DictReader(fh, delimiter=config.delimiter)
        records = list(reader)
    logger.info("Read %d records from CSV '%s'", len(records), config.name)
    return records


@source_registry.register("json")
def read_json(config: SourceConfig) -> list[Record]:
    """Read records from a JSON file."""
    path = Path(config.path)  # type: ignore[arg-type]
    logger.info("Reading JSON source '%s' from %s", config.name, path)
    data = json.loads(path.read_text(encoding=config.encoding))
    records = _resolve_json_root(data, config.json_root)
    logger.info("Read %d records from JSON '%s'", len(records), config.name)
    return records


@source_registry.register("sql")
def read_sql(config: SourceConfig) -> list[Record]:
    """Read records from a SQL database using SQLAlchemy.

    Supports optional chunked reads via config.chunk_size.
    """
    logger.info("Reading SQL source '%s'", config.name)
    engine = sqlalchemy.create_engine(config.connection_string)  # type: ignore[arg-type]
    with engine.connect() as conn:
        result = conn.execute(sqlalchemy.text(config.query))  # type: ignore[arg-type]
        columns = list(result.keys())

        if config.chunk_size:
            records: list[Record] = []
            while True:
                chunk = result.fetchmany(config.chunk_size)
                if not chunk:
                    break
                records.extend(dict(zip(columns, row)) for row in chunk)
                logger.debug(
                    "Read chunk of %d rows from SQL '%s' (total: %d)",
                    len(chunk),
                    config.name,
                    len(records),
                )
        else:
            records = [dict(zip(columns, row)) for row in result.fetchall()]

    logger.info("Read %d records from SQL '%s'", len(records), config.name)
    return records


@source_registry.register("rest")
def read_rest(config: SourceConfig) -> list[Record]:
    """Read records from a REST API endpoint.

    Supports rate limiting and pagination.
    """
    logger.info("Reading REST source '%s' from %s", config.name, config.url)

    limiter = None
    if config.rate_limit:
        limiter = RateLimiter(
            requests_per_second=config.rate_limit.requests_per_second,
            burst=config.rate_limit.burst,
        )

    # Single request (no pagination)
    if not config.pagination:
        if limiter:
            limiter.acquire()
        response = requests.request(
            method=config.method,
            url=config.url,  # type: ignore[arg-type]
            headers=config.headers or None,
            params=config.params or None,
            json=config.body,
            timeout=config.timeout,
        )
        response.raise_for_status()
        data = response.json()
        records = _resolve_json_root(data, config.json_root)
        logger.info("Read %d records from REST '%s'", len(records), config.name)
        return records

    # Paginated requests
    pagination = config.pagination
    all_records: list[Record] = []

    for page_num in range(1, pagination.max_pages + 1):
        if limiter:
            limiter.acquire()

        params = dict(config.params or {})
        params[pagination.page_param] = str(page_num)
        params[pagination.page_size_param] = str(pagination.page_size)

        response = requests.request(
            method=config.method,
            url=config.url,  # type: ignore[arg-type]
            headers=config.headers or None,
            params=params,
            json=config.body,
            timeout=config.timeout,
        )
        response.raise_for_status()
        data = response.json()

        try:
            page_records = _resolve_json_root(data, config.json_root)
        except (ValueError, KeyError):
            break

        if not page_records:
            break

        all_records.extend(page_records)
        logger.debug(
            "REST '%s' page %d: %d records (total: %d)",
            config.name,
            page_num,
            len(page_records),
            len(all_records),
        )

        if len(page_records) < pagination.page_size:
            break

    logger.info("Read %d records from REST '%s'", len(all_records), config.name)
    return all_records


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def read_source(config: SourceConfig) -> list[Record]:
    """Read records from a source based on its type.

    Checks the plugin registry first, then raises for unknown types.
    """
    reader = source_registry.get(config.type)
    if reader is None:
        raise ValueError(
            f"Unsupported source type: '{config.type}'. "
            f"Available: {source_registry.keys()}"
        )
    return reader(config)
