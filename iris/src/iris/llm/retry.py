"""Retry policy for calls to OpenAI-compatible model APIs.

The SDK clients run with ``max_retries=0`` so that this module is the only retry
layer. It follows the providers' guidance: retry rate limits, server errors,
connection errors and 408/409, honour the server's ``retry-after-ms`` /
``retry-after`` headers, add jitter so parallel calls do not retry in step, never
retry other 4xx errors, and retry a timed-out request only once (a request that
already ran into the client timeout would otherwise block a worker for many
minutes).
"""

import random
import threading
import time
from email.utils import parsedate_to_datetime
from typing import Optional

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)

from iris.common.logging_config import get_logger

logger = get_logger(__name__)

MAX_ATTEMPTS = 5
INITIAL_DELAY_SECONDS = 1.0
BACKOFF_FACTOR = 2.0
MAX_BACKOFF_SECONDS = 16.0
# A server may ask for a longer pause than this; the call then gives up instead
# of holding the worker (and the student's run) for minutes.
MAX_WAIT_SECONDS = 30.0
MAX_TIMEOUT_RETRIES = 1

_RETRYABLE_ERRORS = (RateLimitError, APIConnectionError, InternalServerError)


def is_retryable(error: BaseException) -> bool:
    """Whether a failed call may be sent again."""
    if isinstance(error, _RETRYABLE_ERRORS):
        return True
    if isinstance(error, APIStatusError):
        return error.status_code >= 500 or error.status_code in (408, 409)
    return False


def retry_after_seconds(error: BaseException) -> Optional[float]:
    """The pause the server asked for, read from the error response headers."""
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    milliseconds = headers.get("retry-after-ms")
    if milliseconds is not None:
        try:
            return max(0.0, float(milliseconds) / 1000.0)
        except ValueError:
            pass
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, retry_at.timestamp() - time.time())


def backoff_seconds(attempt: int) -> float:
    """Exponential backoff with jitter for the given zero-based attempt."""
    ceiling = min(MAX_BACKOFF_SECONDS, INITIAL_DELAY_SECONDS * BACKOFF_FACTOR**attempt)
    return random.uniform(ceiling / 2, ceiling)  # nosec B311 - jitter, not security


class RetryState:
    """Decides, per failed attempt, whether and how long to wait before retrying."""

    def __init__(
        self,
        max_attempts: int = MAX_ATTEMPTS,
        cancel_event: Optional[threading.Event] = None,
    ):
        self.max_attempts = max_attempts
        self.cancel_event = cancel_event
        self._timeouts = 0

    def should_retry(self, error: BaseException, attempt: int) -> bool:
        """Return whether ``error`` from the zero-based ``attempt`` is retried."""
        if not is_retryable(error):
            return False
        if attempt + 1 >= self.max_attempts:
            return False
        if isinstance(error, APITimeoutError):
            self._timeouts += 1
            if self._timeouts > MAX_TIMEOUT_RETRIES:
                return False
        if self.cancel_event is not None and self.cancel_event.is_set():
            return False
        requested = retry_after_seconds(error)
        if requested is not None and requested > MAX_WAIT_SECONDS:
            logger.warning(
                "Not retrying: the server asked to wait %.0f s (limit %.0f s)",
                requested,
                MAX_WAIT_SECONDS,
            )
            return False
        return True

    def wait(self, error: BaseException, attempt: int) -> None:
        """Sleep before the next attempt; a cancel wakes the wait early."""
        requested = retry_after_seconds(error)
        seconds = requested if requested is not None else backoff_seconds(attempt)
        seconds = min(seconds, MAX_WAIT_SECONDS)
        logger.info(
            "Retrying model call in %.1f s (attempt %d of %d): %s",
            seconds,
            attempt + 2,
            self.max_attempts,
            type(error).__name__,
        )
        if self.cancel_event is not None:
            self.cancel_event.wait(seconds)
        else:
            time.sleep(seconds)
