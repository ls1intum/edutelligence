import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from weaviate.collections import Collection
from weaviate.exceptions import UnexpectedStatusCodeError

from iris.common.logging_config import get_logger

logger = get_logger(__name__)

REQUEST_TIMEOUT_SECONDS = 8.0
MAX_WRITE_ATTEMPTS = 6
INITIAL_RETRY_DELAY_SECONDS = 0.05
MAX_RETRY_DELAY_SECONDS = 1.0


class WeaviateRateLimitExhausted(RuntimeError):
    """Raised when a Weaviate write stays rate-limited past its retry budget."""

    def __init__(
        self,
        attempts: int,
        last_error: UnexpectedStatusCodeError | None = None,
    ):
        super().__init__(
            f"Weaviate remained rate-limited after {attempts} write attempt(s)"
        )
        self.attempts = attempts
        self.last_error = last_error


@dataclass
class WeaviateRateLimitGate:
    """Share a short Weaviate cooldown between request threads in this process."""

    _cooldown_until: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def remaining_delay(self, now: float) -> float:
        with self._lock:
            return max(0.0, self._cooldown_until - now)

    def extend(self, until: float) -> None:
        with self._lock:
            self._cooldown_until = max(self._cooldown_until, until)


_shared_rate_limit_gate = WeaviateRateLimitGate()


class WeaviateWriteRetry:
    """Retry idempotent Weaviate updates within one shared request deadline."""

    def __init__(
        self,
        *,
        deadline: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[float, float], float] = random.uniform,
        gate: WeaviateRateLimitGate = _shared_rate_limit_gate,
    ):
        self.deadline = deadline
        self.clock = clock
        self.sleep = sleep
        self.jitter = jitter
        self.gate = gate

    @classmethod
    def for_request(cls) -> "WeaviateWriteRetry":
        """Create a retry context with one deadline for the complete request."""
        return cls(deadline=time.monotonic() + REQUEST_TIMEOUT_SECONDS)

    def update(self, collection: Collection, *, uuid: str, properties: dict) -> None:
        """Update one object, waiting briefly when Weaviate returns HTTP 429."""
        last_error: UnexpectedStatusCodeError | None = None

        for attempt in range(1, MAX_WRITE_ATTEMPTS + 1):
            self._wait_for_shared_cooldown(last_error, attempt - 1)
            try:
                collection.data.update(uuid=uuid, properties=properties)
                return
            except UnexpectedStatusCodeError as error:
                if error.status_code != 429:
                    raise
                last_error = error

                if attempt == MAX_WRITE_ATTEMPTS:
                    self._raise_exhausted(attempt, error)

                retry_limit = min(
                    MAX_RETRY_DELAY_SECONDS,
                    INITIAL_RETRY_DELAY_SECONDS * (2 ** (attempt - 1)),
                )
                retry_delay = self.jitter(0.0, retry_limit)
                self.gate.extend(self.clock() + retry_delay)
                logger.warning(
                    "Weaviate rate-limited an object update; retrying | "
                    "attempt=%s max_attempts=%s retry_in_ms=%s",
                    attempt,
                    MAX_WRITE_ATTEMPTS,
                    round(retry_delay * 1000),
                )

        raise AssertionError("Weaviate retry loop exited unexpectedly")

    def _wait_for_shared_cooldown(
        self,
        last_error: UnexpectedStatusCodeError | None,
        attempts: int,
    ) -> None:
        now = self.clock()
        if last_error is not None and now >= self.deadline:
            self._raise_exhausted(attempts, last_error)
        delay = self.gate.remaining_delay(now)
        if delay <= 0:
            return
        if now + delay >= self.deadline:
            self._raise_exhausted(attempts, last_error)
        self.sleep(delay)

    @staticmethod
    def _raise_exhausted(
        attempts: int,
        last_error: UnexpectedStatusCodeError | None,
    ) -> None:
        exhausted = WeaviateRateLimitExhausted(attempts, last_error)
        if last_error is None:
            raise exhausted
        raise exhausted from last_error
