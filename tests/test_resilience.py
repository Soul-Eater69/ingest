"""Tests for resilience utilities (retry, circuit breaker)."""

import pytest

from neo4j_ingest.resilience import (
    CircuitBreaker,
    CircuitBreakerOpen,
    CircuitState,
    MaxRetriesExceeded,
    retry,
)


class TestRetry:
    def test_success_first_try(self):
        result = retry(lambda: 42, max_attempts=3)
        assert result == 42

    def test_succeeds_after_failures(self):
        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("temporary")
            return "ok"

        result = retry(
            flaky,
            max_attempts=5,
            base_delay=0.01,
            retryable_exceptions=(ValueError,),
        )
        assert result == "ok"
        assert call_count == 3

    def test_max_retries_exceeded(self):
        def always_fail():
            raise ValueError("permanent")

        with pytest.raises(MaxRetriesExceeded) as exc_info:
            retry(
                always_fail,
                max_attempts=2,
                base_delay=0.01,
                retryable_exceptions=(ValueError,),
            )
        assert exc_info.value.attempts == 2

    def test_non_retryable_exception_raises_immediately(self):
        call_count = 0

        def fail_with_type_error():
            nonlocal call_count
            call_count += 1
            raise TypeError("not retryable")

        with pytest.raises(TypeError):
            retry(
                fail_with_type_error,
                max_attempts=3,
                base_delay=0.01,
                retryable_exceptions=(ValueError,),
            )
        assert call_count == 1


class TestCircuitBreaker:
    def test_closed_passes_through(self):
        cb = CircuitBreaker(failure_threshold=3)
        result = cb.call(lambda: 42)
        assert result == 42
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=100)

        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(lambda: (_ for _ in ()).throw(ValueError("fail")))

        assert cb.state == CircuitState.OPEN

        with pytest.raises(CircuitBreakerOpen):
            cb.call(lambda: 42)

    def test_resets_on_success(self):
        cb = CircuitBreaker(failure_threshold=3)

        # One failure
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("fail")))

        # Then success resets
        cb.call(lambda: "ok")
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 0
