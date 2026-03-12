"""
API-level service for configuring global LLM behaviour.

Example::

    from memiris.api.llm_config_service import LlmConfigService
    from memiris.llm.retry_config import RetryConfig

    LlmConfigService.configure_retry(
        RetryConfig(max_attempts=5, initial_delay=2.0, backoff_factor=2.0)
    )
"""

from typing import Optional, Tuple, Type

from memiris.llm.retry_config import (
    RetryConfig,
    get_retry_config,
    set_retry_config,
)


class LlmConfigService:
    """Service for reading and updating the global LLM configuration.

    All methods are class-methods so no instantiation is required.
    """

    @classmethod
    def configure_retry(
        cls,
        config: RetryConfig,
    ) -> None:
        """Replace the process-wide LLM retry configuration.

        Parameters
        ----------
        config:
            The new :class:`~memiris.llm.retry_config.RetryConfig` to apply
            to every subsequent LLM call in the process.
        """
        set_retry_config(config)

    @classmethod
    def configure_retry_params(
        cls,
        *,
        max_attempts: Optional[int] = None,
        initial_delay: Optional[float] = None,
        backoff_factor: Optional[float] = None,
        exceptions: Optional[Tuple[Type[BaseException], ...]] = None,
    ) -> None:
        """Update individual retry parameters while keeping the rest unchanged.

        Only the keyword arguments that are explicitly provided will be
        changed; all others are taken from the currently active config.

        Parameters
        ----------
        max_attempts:
            Total number of attempts (1 = no retry).
        initial_delay:
            Seconds to wait before the first retry.
        backoff_factor:
            Multiplier applied to the delay after each failed attempt.
        exceptions:
            Tuple of exception types that should trigger a retry.
        """
        current = get_retry_config()
        set_retry_config(
            RetryConfig(
                max_attempts=(
                    max_attempts if max_attempts is not None else current.max_attempts
                ),
                initial_delay=(
                    initial_delay
                    if initial_delay is not None
                    else current.initial_delay
                ),
                backoff_factor=(
                    backoff_factor
                    if backoff_factor is not None
                    else current.backoff_factor
                ),
                exceptions=exceptions if exceptions is not None else current.exceptions,
            )
        )

    @classmethod
    def get_retry_config(cls) -> RetryConfig:
        """Return the currently active process-wide retry configuration."""
        return get_retry_config()

    @classmethod
    def reset_retry_config(cls) -> None:
        """Reset the retry configuration to the built-in defaults."""
        set_retry_config(RetryConfig())
