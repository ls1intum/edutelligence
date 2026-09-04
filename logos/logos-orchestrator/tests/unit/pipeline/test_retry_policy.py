"""Unit tests for the internal retry policy (#815)."""

import asyncio

import httpx
import pytest

from logos.errors import UpstreamStreamError
from logos.logosnode_registry import LogosNodeCommandError, LogosNodeOfflineError
from logos.pipeline.retry import (
    MIN_RETRY_REMAINING_S,
    RetryBudget,
    exception_is_retryable,
    pipeline_error_is_retryable,
    status_is_retryable,
)
from logos.pipeline.scheduler_interface import DEFAULT_QUEUE_TIMEOUT_S, QueueTimeoutError

# ---------------------------------------------------------------------------
# status_is_retryable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status, expected",
    [
        (408, True),  # request timed out upstream
        (429, True),  # rate limited
        (500, True),  # internal error
        (502, True),  # worker-side fault surfacing as a refused command
        (503, True),  # no capacity / offline
        (504, True),  # gateway timeout
        (501, False),  # structurally impossible
        (505, False),  # structurally impossible
        (400, False),  # bad request — permanent for this payload
        (401, False),
        (403, False),
        (404, False),
        (422, False),
        (200, False),
        (None, False),
    ],
)
def test_status_is_retryable(status, expected):
    assert status_is_retryable(status) is expected


# ---------------------------------------------------------------------------
# pipeline_error_is_retryable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        "All candidate models unavailable (rate-limited or no capacity)",
        "Failed to resolve execution context: lane not ready after 600s",
    ],
)
def test_pipeline_error_is_retryable_transient(error):
    assert pipeline_error_is_retryable(error) is True


@pytest.mark.parametrize(
    "error",
    [
        # A queue-wait timeout says the queue is saturated, not that a node
        # is broken — it is returned to the caller, never re-queued
        # internally under the same pressure.
        "Queue wait timeout after 1200s",
        "Queue wait timeout",
        "No models passed classification",
        "Some other pipeline error",
        "",
        None,
    ],
)
def test_pipeline_error_is_retryable_permanent(error):
    assert pipeline_error_is_retryable(error) is False


# ---------------------------------------------------------------------------
# exception_is_retryable
# ---------------------------------------------------------------------------


def test_exception_is_retryable_infrastructure_failures():
    assert exception_is_retryable(LogosNodeOfflineError("session dropped")) is True
    assert exception_is_retryable(LogosNodeCommandError("infer failed")) is True
    assert exception_is_retryable(UpstreamStreamError(429, {"error": "slow down"})) is True
    assert exception_is_retryable(UpstreamStreamError(503, {"error": "unavailable"})) is True
    assert exception_is_retryable(asyncio.TimeoutError()) is True
    assert exception_is_retryable(httpx.ConnectError("broken pipe")) is True
    assert exception_is_retryable(httpx.ReadTimeout("read timed out")) is True


def test_exception_is_retryable_permanent_failures():
    # A context-length 500 is corrected to 400 by coerce_upstream_error before
    # it ever reaches the executor, so a 400 here means the payload is the
    # problem — retrying cannot help.
    assert exception_is_retryable(UpstreamStreamError(400, {"error": "too long"})) is False
    assert exception_is_retryable(ValueError("bad payload")) is False
    assert exception_is_retryable(RuntimeError("something else")) is False
    # A queue-wait timeout reports queue saturation, not a broken link: it is
    # returned to the caller (which backs off) instead of being re-queued.
    assert exception_is_retryable(QueueTimeoutError("req-1", 1, 2, 1200.0)) is False


# ---------------------------------------------------------------------------
# RetryBudget
# ---------------------------------------------------------------------------


class _Clock:
    """Injectable monotonic clock so tests can drive time deterministically."""

    def __init__(self, start: float = 1000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _budget(max_attempts: int = 3, deadline_s: float = 1800.0, **kw) -> tuple[RetryBudget, _Clock]:
    clock = _Clock()
    return RetryBudget(max_attempts=max_attempts, deadline_s=deadline_s, now=clock, **kw), clock


def test_fresh_budget_allows_retries():
    budget, _ = _budget(max_attempts=3)
    assert budget.attempts == 0
    assert budget.can_retry() is True


def test_attempt_bound():
    """max_attempts=3 → initial dispatch plus at most two retries.

    ``can_retry()`` is consulted *before* the failed attempt is recorded, so
    the checks interleave with the record_failure calls.
    """
    budget, _ = _budget(max_attempts=3)
    assert budget.can_retry() is True  # dispatch 1 may fail and be retried
    budget.record_failure(1)
    assert budget.can_retry() is True  # dispatch 2 may fail and be retried
    budget.record_failure(2)
    assert budget.can_retry() is False  # dispatch 3 is the last one
    budget.record_failure(3)
    assert budget.can_retry() is False


def test_deadline_bound():
    budget, clock = _budget(max_attempts=5, deadline_s=100.0)
    clock.advance(100.0 - MIN_RETRY_REMAINING_S + 0.1)
    assert budget.remaining_s() < MIN_RETRY_REMAINING_S
    assert budget.can_retry() is False


def test_single_attempt_budget_never_retries():
    budget, _ = _budget(max_attempts=1)
    assert budget.can_retry() is False
    budget.record_failure(1)
    assert budget.can_retry() is False


def test_failed_providers_are_excluded():
    budget, _ = _budget()
    budget.record_failure(7)
    budget.record_failure(None)  # scheduling-level failure: no provider hit
    budget.record_failure(9)
    assert budget.excluded_providers() == frozenset({7, 9})


def test_backoff_is_exponential_and_capped():
    budget, _ = _budget(backoff_base_s=1.0, backoff_cap_s=4.0)
    budget.record_failure(1)
    assert budget.backoff_s() == 1.0
    budget.record_failure(2)
    assert budget.backoff_s() == 2.0
    budget.record_failure(3)
    assert budget.backoff_s() == 4.0
    budget.record_failure(4)
    assert budget.backoff_s() == 4.0  # capped


def test_backoff_clamped_to_remaining_deadline():
    budget, clock = _budget(max_attempts=10, deadline_s=100.0)
    clock.advance(98.0)
    for i in range(4):
        budget.record_failure(i + 1)
    assert budget.backoff_s() == pytest.approx(2.0)  # 8s exponential, but only 2s left


def test_queue_wait_timeout_clamped_to_deadline():
    budget, clock = _budget(max_attempts=10, deadline_s=100.0)
    # No user timeout: platform default, clamped to the remaining deadline.
    assert budget.queue_wait_timeout_s(None) == pytest.approx(min(DEFAULT_QUEUE_TIMEOUT_S, 100.0))
    clock.advance(90.0)
    assert budget.queue_wait_timeout_s(None) == pytest.approx(10.0)


def test_queue_wait_timeout_respects_user_timeout():
    budget, _ = _budget(max_attempts=10, deadline_s=100.0)
    assert budget.queue_wait_timeout_s(60.0) == pytest.approx(60.0)
    budget, clock = _budget(max_attempts=10, deadline_s=100.0)
    clock.advance(95.0)
    assert budget.queue_wait_timeout_s(60.0) == pytest.approx(5.0)  # clamped below the user bound


def test_queue_wait_timeout_falls_back_to_default_for_invalid_user_values():
    budget, _ = _budget()
    assert budget.queue_wait_timeout_s(0) == pytest.approx(min(DEFAULT_QUEUE_TIMEOUT_S, budget.remaining_s()))
    assert budget.queue_wait_timeout_s(-5) == pytest.approx(min(DEFAULT_QUEUE_TIMEOUT_S, budget.remaining_s()))
    assert budget.queue_wait_timeout_s("garbage") == pytest.approx(min(DEFAULT_QUEUE_TIMEOUT_S, budget.remaining_s()))
