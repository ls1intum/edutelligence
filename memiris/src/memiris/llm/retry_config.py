"""
Retry configuration and helper for LLM calls.

Global retry behaviour is controlled through :func:`get_retry_config` /
:func:`set_retry_config`.  All LLM adapters read the global config at call
time, so a single call to :func:`set_retry_config` affects every subsequent
LLM request in the process.

Example::

    from memiris.llm.retry_config import RetryConfig, set_retry_config

    set_retry_config(RetryConfig(max_attempts=5, initial_delay=2.0, backoff_factor=2.0))
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Tuple, Type, TypeVar

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


@dataclass
class RetryConfig:
    """Configuration for retrying LLM calls.

    Attributes:
        max_attempts:   Total number of attempts (1 = no retry).
        initial_delay:  Seconds to wait before the first retry.
        backoff_factor: Multiplier applied to the delay after each failed
                        attempt (must be >= 1).
        exceptions:     Tuple of exception types that trigger a retry.
                        Defaults to retrying on any :class:`Exception`.
    """

    max_attempts: int = 5
    initial_delay: float = 1.0
    backoff_factor: float = 2.0
    exceptions: Tuple[Type[BaseException], ...] = field(
        default_factory=lambda: (Exception,)
    )

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.initial_delay < 0:
            raise ValueError("initial_delay must be >= 0")
        if self.backoff_factor < 1:
            raise ValueError("backoff_factor must be >= 1")


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_global_retry_config: RetryConfig = RetryConfig()


def get_retry_config() -> RetryConfig:
    """Return the process-wide LLM retry configuration."""
    return _global_retry_config


def set_retry_config(config: RetryConfig) -> None:
    """Replace the process-wide LLM retry configuration.

    Parameters
    ----------
    config:
        The new :class:`RetryConfig` to use for all subsequent LLM calls.
    """
    global _global_retry_config  # noqa: PLW0603
    if not isinstance(config, RetryConfig):
        raise TypeError(f"Expected RetryConfig, got {type(config)!r}")
    _global_retry_config = config


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def call_with_retry(fn: Callable[[], _T]) -> _T:
    """Call *fn* and retry on transient failures using the global config.

    Parameters
    ----------
    fn:
        A zero-argument callable that performs the LLM call.

    Returns
    -------
    The return value of *fn* on success.

    Raises
    ------
    The last exception raised by *fn* after all attempts are exhausted.
    """
    config = get_retry_config()
    delay = config.initial_delay
    last_exc: BaseException | None = None

    for attempt in range(1, config.max_attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            if not isinstance(exc, config.exceptions):
                raise
            last_exc = exc
            if attempt == config.max_attempts:
                logger.warning("LLM call failed after %d attempt(s): %s", attempt, exc)
                break
            logger.warning(
                "LLM call failed (attempt %d/%d): %s – retrying in %.1fs …",
                attempt,
                config.max_attempts,
                exc,
                delay,
            )
            time.sleep(delay)
            delay *= config.backoff_factor

    raise last_exc  # type: ignore[misc]
