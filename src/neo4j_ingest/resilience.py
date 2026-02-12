"""Resilience utilities: retry with backoff, circuit breaker, health checks.

Enterprise ingestion jobs must handle transient failures gracefully.
This module provides:
- retry(): decorator/function with exponential backoff and jitter
- CircuitBreaker: stops calling a failing dependency after N failures
- Neo4j health check before starting a job
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Retry with exponential backoff
# ---------------------------------------------------------------------------

class MaxRetriesExceeded(Exception):
    """All retry attempts exhausted."""

    def __init__(self, attempts: int, last_error: Exception) -> None:
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            f"Failed after {attempts} attempts. Last error: {last_error}"
        )


def retry(
    fn: Callable[..., T],
    *args: Any,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    **kwargs: Any,
) -> T:
    """Call *fn* with retries on failure.

    Uses exponential backoff with jitter:
        delay = min(base_delay * backoff_factor ** attempt, max_delay) + jitter
    """
    last_error: Exception | None = None

    for attempt in range(max_attempts):
        try:
            return fn(*args, **kwargs)
        except retryable_exceptions as exc:
            last_error = exc
            if attempt == max_attempts - 1:
                break
            delay = min(base_delay * (backoff_factor ** attempt), max_delay)
            jitter = random.uniform(0, delay * 0.1)
            total_delay = delay + jitter
            logger.warning(
                "Attempt %d/%d failed (%s). Retrying in %.1fs …",
                attempt + 1,
                max_attempts,
                exc,
                total_delay,
            )
            time.sleep(total_delay)

    raise MaxRetriesExceeded(max_attempts, last_error)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

class CircuitState(Enum):
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing — reject calls
    HALF_OPEN = "half_open"  # Testing if the dependency recovered


class CircuitBreakerOpen(Exception):
    """Raised when the circuit breaker is open."""


@dataclass
class CircuitBreaker:
    """Simple circuit breaker.

    After *failure_threshold* consecutive failures the circuit opens
    and rejects calls for *recovery_timeout* seconds, then moves to
    half-open state to probe recovery.
    """

    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)

    def call(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        if self.state == CircuitState.OPEN:
            if time.time() - self._last_failure_time >= self.recovery_timeout:
                logger.info("Circuit breaker moving to HALF_OPEN")
                self.state = CircuitState.HALF_OPEN
            else:
                raise CircuitBreakerOpen(
                    f"Circuit breaker is OPEN. Will retry after {self.recovery_timeout}s."
                )

        try:
            result = fn(*args, **kwargs)
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure()
            raise exc

    def _on_success(self) -> None:
        self._failure_count = 0
        if self.state == CircuitState.HALF_OPEN:
            logger.info("Circuit breaker CLOSED (recovered)")
        self.state = CircuitState.CLOSED

    def _on_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.failure_threshold:
            logger.error(
                "Circuit breaker OPEN after %d consecutive failures",
                self._failure_count,
            )
            self.state = CircuitState.OPEN


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def check_neo4j_health(uri: str, username: str, password: str, database: str) -> bool:
    """Verify Neo4j is reachable and the database exists."""
    from neo4j import GraphDatabase
    from neo4j.exceptions import ServiceUnavailable, AuthError

    try:
        driver = GraphDatabase.driver(uri, auth=(username, password))
        with driver.session(database=database) as session:
            session.run("RETURN 1")
        driver.close()
        logger.info("Neo4j health check passed (%s)", uri)
        return True
    except ServiceUnavailable:
        logger.error("Neo4j health check FAILED: service unavailable at %s", uri)
        return False
    except AuthError:
        logger.error("Neo4j health check FAILED: authentication error")
        return False
    except Exception as exc:
        logger.error("Neo4j health check FAILED: %s", exc)
        return False
