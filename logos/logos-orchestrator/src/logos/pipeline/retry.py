# src/logos/pipeline/retry.py
"""
Internal retry policy for failed requests (#815).

A request that fails before the answer is complete is retried internally
instead of being returned raw to the requester:

- wait-mode timeout — no node had capacity in time,
- hardware failure — a worker crashed or refused the command,
- re-deployment — the worker's session dropped mid-request (#793),
- network hiccups — the connection to the worker broke.

Retries are bounded by an attempt count and an overall wall-clock deadline,
and each retry may be placed on another node serving the same model (the
pipeline receives the failed node as an exclusion and re-scores the
remaining deployments).

Plain retries keep the request's original queue priority; only a mid-flight
stream resume — where tokens already reached the caller — is escalated to
``Priority.RESUME``.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import httpx

from logos.errors import UpstreamStreamError
from logos.logosnode_registry import LogosNodeCommandError, LogosNodeOfflineError
from logos.pipeline.scheduler_interface import DEFAULT_QUEUE_TIMEOUT_S, QueueTimeoutError

# Never start a retry with less than this much time left in the deadline —
# the next queue wait would expire before it could make progress.
MIN_RETRY_REMAINING_S = 5.0

# 408 (request timed out upstream) and 429 (rate limited) are transient; so
# is every 5xx that is not structurally impossible (501 Not Implemented,
# 505 HTTP Version Not Supported). Context-length 500s are corrected to 400
# by ``coerce_upstream_error`` before any of these checks runs, so a request
# that is simply too long is never retried.
RETRYABLE_HTTP_STATUSES = frozenset({408, 429})
_NON_RETRYABLE_5XX = frozenset({501, 505})


def status_is_retryable(status_code: Optional[int]) -> bool:
    """Whether an upstream/worker HTTP status is a transient failure worth an
    internal retry.

    4xx client errors (bad request, auth, missing model, context length) are
    permanent for the same payload — retrying them only delays the error.
    """
    if not isinstance(status_code, int):
        return False
    if status_code in RETRYABLE_HTTP_STATUSES:
        return True
    return 500 <= status_code < 600 and status_code not in _NON_RETRYABLE_5XX


def pipeline_error_is_retryable(error: Optional[str]) -> bool:
    """Whether a pipeline-level failure (before any execution) is transient.

    - "Queue wait timeout" — wait mode: no node had capacity in time. A
      re-queue within the retry deadline can catch a freed lane, and another
      node may serve the model.
    - "All candidate models unavailable" — the same state, detected at
      scoring instead of in the queue.
    - "Failed to resolve execution context" — the lane never became ready:
      worker redeployed, hardware fault, or the model load failed.

    "No models passed classification" is a policy decision and is permanent
    for this request.
    """
    if not error:
        return False
    lowered = error.lower()
    return (
        "queue wait timeout" in lowered
        or "all candidate models unavailable" in lowered
        or "failed to resolve execution context" in lowered
    )


def exception_is_retryable(exc: BaseException) -> bool:
    """Whether an execution exception is a transient infrastructure failure
    rather than a problem with the request itself.

    Covers the failure classes named in #815: a worker that is offline or
    was redeployed (``LogosNodeOfflineError``), a worker-side fault such as a
    hardware failure surfacing as a refused command (``LogosNodeCommandError``),
    and network hiccups on the orchestrator↔worker link (``httpx`` transport
    errors, timeouts).
    """
    if isinstance(exc, (LogosNodeOfflineError, LogosNodeCommandError)):
        return True
    if isinstance(exc, UpstreamStreamError):
        return status_is_retryable(exc.status_code)
    if isinstance(exc, (QueueTimeoutError, asyncio.TimeoutError)):
        return True
    if isinstance(exc, httpx.HTTPError):
        return True
    return False


@dataclass
class RetryBudget:
    """Binds how often and for how long a request is retried internally.

    ``attempts`` counts consumed attempts (the initial dispatch included), so
    ``max_attempts=3`` means one initial dispatch plus at most two retries.
    The deadline is the overall wall-clock budget for the whole sequence;
    every re-queue is clamped to what is left in it, and the backoff is
    clamped as well, so a request never waits past its deadline.
    """

    max_attempts: int
    deadline_s: float
    backoff_base_s: float = 1.0
    backoff_cap_s: float = 15.0
    # Injectable clock so tests can drive time without patching the module.
    now: Callable[[], float] = time.monotonic

    attempts: int = field(default=0, init=False)
    failed_provider_ids: list[int] = field(default_factory=list, init=False)
    _started_at: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        self._started_at = self.now()

    @property
    def deadline_at(self) -> float:
        return self._started_at + self.deadline_s

    def remaining_s(self) -> float:
        return max(0.0, self.deadline_at - self.now())

    def can_retry(self) -> bool:
        """Whether another dispatch is allowed: attempts left and enough time
        in the deadline for the next queue wait to be meaningful."""
        return self.attempts < self.max_attempts - 1 and self.remaining_s() >= MIN_RETRY_REMAINING_S

    def record_failure(self, provider_id: Optional[int]) -> None:
        """Account for a failed attempt and which node it hit (for failover)."""
        self.attempts += 1
        if provider_id is not None:
            self.failed_provider_ids.append(int(provider_id))

    def excluded_providers(self) -> frozenset[int]:
        """Nodes that already failed this request.

        The next attempt may prefer another node serving the same model. When
        the exclusion would leave no node at all (single-node model), the
        pipeline retries the same node — that is the redeploy case, where the
        answer comes back from the very node that dropped.
        """
        return frozenset(self.failed_provider_ids)

    def backoff_s(self) -> float:
        """Exponential backoff between attempts, capped, and clamped to the
        time left in the deadline."""
        delay = min(self.backoff_cap_s, self.backoff_base_s * (2 ** max(0, self.attempts - 1)))
        return max(0.0, min(delay, self.remaining_s()))

    def queue_wait_timeout_s(self, user_timeout_s: Optional[float]) -> float:
        """Queue-wait bound for the next attempt.

        The smaller of the caller's ``timeout_s`` (or the platform default
        when the caller set none) and the time left in the deadline — a
        re-queue must never wait past the overall budget.
        """
        try:
            user = float(user_timeout_s) if user_timeout_s is not None else None
        except (TypeError, ValueError):
            user = None
        base = user if user is not None and user > 0 else DEFAULT_QUEUE_TIMEOUT_S
        return max(1.0, min(base, self.remaining_s()))
