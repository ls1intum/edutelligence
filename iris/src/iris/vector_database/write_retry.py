import random
import time
from collections.abc import Callable
from typing import NoReturn, TypeVar

from weaviate.collections import Collection
from weaviate.exceptions import UnexpectedStatusCodeError

from iris.common.logging_config import get_logger

logger = get_logger(__name__)

MAX_RETRY_WAIT_SECONDS = 8.0
MAX_WRITE_ATTEMPTS = 6
INITIAL_RETRY_DELAY_SECONDS = 0.25
MAX_RETRY_DELAY_SECONDS = 4.0

T = TypeVar("T")

# Substrings that mark a Weaviate error as transient — worth a bounded retry rather
# than failing the whole run. A read-only store under disk/resource pressure, a rate
# limit, or a momentary overload all clear on their own; a schema or validation error
# does not and must surface immediately.
_TRANSIENT_MESSAGE_MARKERS = (
    "read-only",
    "read only",
    "resource pressure",
    "overloaded",
    "rate limit",
    "temporarily unavailable",
    "timed out",
    "timeout",
    "connection reset",
    "connection aborted",
)


def is_transient_message(message: str) -> bool:
    """True when an error message names a condition that typically clears on retry."""
    lowered = message.lower()
    return any(marker in lowered for marker in _TRANSIENT_MESSAGE_MARKERS)


def is_transient_error(error: BaseException) -> bool:
    """Classify an exception as a transient Weaviate condition worth retrying."""
    if isinstance(error, UnexpectedStatusCodeError):
        if error.status_code in (429, 503):
            return True
    return is_transient_message(str(error))


class WeaviateRateLimitExhausted(RuntimeError):
    """Raised when a Weaviate write stays rate-limited past its retry budget."""

    def __init__(
        self,
        attempts: int,
        last_error: BaseException,
    ):
        super().__init__(
            f"Weaviate remained rate-limited after {attempts} write attempt(s)"
        )
        self.attempts = attempts
        self.last_error = last_error


class WeaviateWriteRetry:
    """Retry transient Weaviate operations within one shared wait budget.

    The budget bounds the total time slept across every operation that shares
    this context, so a whole request can retry under load without a single
    operation blocking indefinitely. Only transient conditions (rate limit,
    read-only under resource pressure, momentary overload) are retried; anything
    else propagates at once.
    """

    def __init__(
        self,
        *,
        retry_wait_budget: float = MAX_RETRY_WAIT_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[float, float], float] = random.uniform,
    ):
        self.remaining_retry_wait = retry_wait_budget
        self.sleep = sleep
        self.jitter = jitter

    @classmethod
    def for_request(cls) -> "WeaviateWriteRetry":
        """Create one retry context for the complete request."""
        return cls()

    def backoff(self, attempt: int, description: str = "Weaviate operation") -> bool:
        """Wait before the next retry of a failed attempt.

        Returns ``True`` after sleeping when another attempt is allowed, and
        ``False`` when the attempt cap or the shared wait budget is spent, so the
        caller gives up. ``attempt`` is the 1-indexed number of the attempt that
        just failed. ``description`` names the operation being retried so a retry
        storm is legible in the logs.
        """
        if attempt >= MAX_WRITE_ATTEMPTS:
            return False
        retry_limit = min(
            MAX_RETRY_DELAY_SECONDS,
            INITIAL_RETRY_DELAY_SECONDS * (2 ** (attempt - 1)),
        )
        retry_delay = self.jitter(retry_limit / 2, retry_limit)
        retry_delay = min(retry_limit, max(retry_limit / 2, retry_delay))
        if retry_delay > self.remaining_retry_wait:
            return False
        self.remaining_retry_wait -= retry_delay
        logger.warning(
            "Weaviate transient failure; retrying %s | "
            "attempt=%s max_attempts=%s retry_in_ms=%s remaining_wait_ms=%s",
            description,
            attempt,
            MAX_WRITE_ATTEMPTS,
            round(retry_delay * 1000),
            round(self.remaining_retry_wait * 1000),
        )
        self.sleep(retry_delay)
        return True

    def run(
        self, operation: Callable[[], T], *, description: str = "Weaviate operation"
    ) -> T:
        """Run an idempotent operation, retrying transient failures within budget.

        Non-transient errors propagate unchanged on the first failure. A transient
        error that outlasts the attempt cap or the wait budget is surfaced as
        :class:`WeaviateRateLimitExhausted`.
        """
        for attempt in range(1, MAX_WRITE_ATTEMPTS + 1):
            try:
                return operation()
            except Exception as error:  # noqa: BLE001 - reraised unless transient
                if not is_transient_error(error):
                    raise
                if not self.backoff(attempt, description):
                    self._raise_exhausted(attempt, error)
        raise AssertionError("Weaviate retry loop exited unexpectedly")

    def update(self, collection: Collection, *, uuid: str, properties: dict) -> None:
        """Update one object, waiting briefly on a transient Weaviate condition."""
        self.run(
            lambda: collection.data.update(uuid=uuid, properties=properties),
            description=f"object update {uuid}",
        )

    @staticmethod
    def _raise_exhausted(
        attempts: int,
        last_error: BaseException,
    ) -> NoReturn:
        raise WeaviateRateLimitExhausted(attempts, last_error) from last_error
