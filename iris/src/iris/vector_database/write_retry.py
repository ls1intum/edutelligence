import random
import time
from collections.abc import Callable
from typing import NoReturn

from weaviate.collections import Collection
from weaviate.exceptions import UnexpectedStatusCodeError

from iris.common.logging_config import get_logger

logger = get_logger(__name__)

MAX_RETRY_WAIT_SECONDS = 8.0
MAX_WRITE_ATTEMPTS = 6
INITIAL_RETRY_DELAY_SECONDS = 0.25
MAX_RETRY_DELAY_SECONDS = 4.0


class WeaviateRateLimitExhausted(RuntimeError):
    """Raised when a Weaviate write stays rate-limited past its retry budget."""

    def __init__(
        self,
        attempts: int,
        last_error: UnexpectedStatusCodeError,
    ):
        super().__init__(
            f"Weaviate remained rate-limited after {attempts} write attempt(s)"
        )
        self.attempts = attempts
        self.last_error = last_error


class WeaviateWriteRetry:
    """Retry idempotent Weaviate updates within one shared wait budget."""

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
        """Create one retry context for the complete visibility request."""
        return cls()

    def update(self, collection: Collection, *, uuid: str, properties: dict) -> None:
        """Update one object, waiting briefly when Weaviate returns HTTP 429."""
        for attempt in range(1, MAX_WRITE_ATTEMPTS + 1):
            try:
                collection.data.update(uuid=uuid, properties=properties)
                return
            except UnexpectedStatusCodeError as error:
                if error.status_code != 429:
                    raise
                if attempt == MAX_WRITE_ATTEMPTS:
                    self._raise_exhausted(attempt, error)

                retry_limit = min(
                    MAX_RETRY_DELAY_SECONDS,
                    INITIAL_RETRY_DELAY_SECONDS * (2 ** (attempt - 1)),
                )
                retry_delay = self.jitter(retry_limit / 2, retry_limit)
                retry_delay = min(retry_limit, max(retry_limit / 2, retry_delay))
                if retry_delay > self.remaining_retry_wait:
                    self._raise_exhausted(attempt, error)

                self.remaining_retry_wait -= retry_delay
                logger.warning(
                    "Weaviate rate-limited an object update; retrying | "
                    "attempt=%s max_attempts=%s retry_in_ms=%s "
                    "remaining_wait_ms=%s",
                    attempt,
                    MAX_WRITE_ATTEMPTS,
                    round(retry_delay * 1000),
                    round(self.remaining_retry_wait * 1000),
                )
                self.sleep(retry_delay)

        raise AssertionError("Weaviate retry loop exited unexpectedly")

    @staticmethod
    def _raise_exhausted(
        attempts: int,
        last_error: UnexpectedStatusCodeError,
    ) -> NoReturn:
        raise WeaviateRateLimitExhausted(attempts, last_error) from last_error
