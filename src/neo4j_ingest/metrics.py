"""Metrics collection and progress reporting.

Provides structured, machine-readable metrics for enterprise observability.
Tracks per-source, per-mapping timing, record counts, error counts, and
overall job statistics.
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Generator

logger = logging.getLogger(__name__)


@dataclass
class StepMetric:
    """Metrics for a single step (source read, node write, rel write)."""

    name: str
    status: str = "pending"
    records_processed: int = 0
    records_failed: int = 0
    start_time: float = 0.0
    end_time: float = 0.0
    error: str | None = None

    @property
    def duration_seconds(self) -> float:
        if self.start_time and self.end_time:
            return round(self.end_time - self.start_time, 3)
        return 0.0

    @property
    def records_per_second(self) -> float:
        dur = self.duration_seconds
        if dur > 0:
            return round(self.records_processed / dur, 1)
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "records_processed": self.records_processed,
            "records_failed": self.records_failed,
            "duration_seconds": self.duration_seconds,
            "records_per_second": self.records_per_second,
            "error": self.error,
        }


@dataclass
class JobMetrics:
    """Aggregate metrics for the entire ingestion job."""

    job_id: str = ""
    config_path: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    status: str = "pending"
    steps: list[StepMetric] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        if self.start_time and self.end_time:
            return round(self.end_time - self.start_time, 3)
        return 0.0

    @property
    def total_records_processed(self) -> int:
        return sum(s.records_processed for s in self.steps)

    @property
    def total_records_failed(self) -> int:
        return sum(s.records_failed for s in self.steps)

    def add_step(self, name: str) -> StepMetric:
        step = StepMetric(name=name)
        self.steps.append(step)
        return step

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "config_path": self.config_path,
            "status": self.status,
            "duration_seconds": self.duration_seconds,
            "total_records_processed": self.total_records_processed,
            "total_records_failed": self.total_records_failed,
            "steps": [s.to_dict() for s in self.steps],
            "errors": self.errors,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def log_summary(self) -> None:
        logger.info(
            "Job %s completed in %.1fs — %d records processed, %d failed",
            self.job_id or "(unnamed)",
            self.duration_seconds,
            self.total_records_processed,
            self.total_records_failed,
        )
        for step in self.steps:
            logger.info(
                "  %-40s %6d records  %6.1fs  %s",
                step.name,
                step.records_processed,
                step.duration_seconds,
                step.status,
            )


@contextmanager
def track_step(metric: StepMetric) -> Generator[StepMetric, None, None]:
    """Context manager that times a step and updates its status."""
    metric.status = "running"
    metric.start_time = time.time()
    try:
        yield metric
        metric.status = "completed"
    except Exception as exc:
        metric.status = "failed"
        metric.error = str(exc)
        raise
    finally:
        metric.end_time = time.time()


class ProgressReporter:
    """Logs progress at configurable intervals."""

    def __init__(self, total: int, step_name: str, report_every: int = 1000) -> None:
        self.total = total
        self.step_name = step_name
        self.report_every = report_every
        self._count = 0
        self._start = time.time()

    def advance(self, n: int = 1) -> None:
        self._count += n
        if self._count % self.report_every == 0 or self._count == self.total:
            elapsed = time.time() - self._start
            rate = self._count / elapsed if elapsed > 0 else 0
            pct = (self._count / self.total * 100) if self.total > 0 else 0
            logger.info(
                "[%s] %d/%d (%.0f%%) — %.0f records/s",
                self.step_name,
                self._count,
                self.total,
                pct,
                rate,
            )
