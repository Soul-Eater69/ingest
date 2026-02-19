"""
utils/logging.py
================
Structured logging setup.

We use Python's standard `logging` module configured with a JSON formatter
so log lines can be ingested by any log aggregator (Loki, Datadog, ELK, …).

Usage
-----
    from codebase_indexer.utils.logging import get_logger
    logger = get_logger(__name__)
    logger.info("indexed file", extra={"path": "src/foo.py", "chunks": 12})
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any


class _JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        payload: dict[str, Any] = {
            "ts":      time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level":   record.levelname,
            "logger":  record.name,
            "msg":     record.getMessage(),
        }
        # Merge any extra= kwargs the caller passed in
        for key, value in record.__dict__.items():
            if key not in logging.LogRecord.__dict__ and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


_configured = False


def _configure_root(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.addHandler(handler)
    _configured = True


def get_logger(name: str, level: str = "INFO") -> logging.Logger:
    """Return a named logger, configuring the root handler on first call."""
    _configure_root(level)
    return logging.getLogger(name)
