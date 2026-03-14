"""Tests for memiris.llm.retry_config."""

from unittest.mock import MagicMock, patch

import pytest

from memiris.llm.retry_config import (
    RetryConfig,
    call_with_retry,
    get_retry_config,
    set_retry_config,
)

# ---------------------------------------------------------------------------
# RetryConfig – construction & validation
# ---------------------------------------------------------------------------


class TestRetryConfig:
    """Tests for the RetryConfig dataclass."""

    def test_defaults(self) -> None:
        cfg = RetryConfig()
        assert cfg.max_attempts == 5
        assert cfg.initial_delay == 1.0
        assert cfg.backoff_factor == 2.0
        assert cfg.exceptions == (Exception,)

    def test_custom_values(self) -> None:
        cfg = RetryConfig(
            max_attempts=5,
            initial_delay=0.5,
            backoff_factor=3.0,
            exceptions=(ValueError, RuntimeError),
        )
        assert cfg.max_attempts == 5
        assert cfg.initial_delay == 0.5
        assert cfg.backoff_factor == 3.0
        assert cfg.exceptions == (ValueError, RuntimeError)

    def test_max_attempts_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="max_attempts"):
            RetryConfig(max_attempts=0)

    def test_max_attempts_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="max_attempts"):
            RetryConfig(max_attempts=-1)

    def test_initial_delay_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="initial_delay"):
            RetryConfig(initial_delay=-0.1)

    def test_backoff_factor_below_one_raises(self) -> None:
        with pytest.raises(ValueError, match="backoff_factor"):
            RetryConfig(backoff_factor=0.5)

    def test_initial_delay_zero_is_valid(self) -> None:
        cfg = RetryConfig(initial_delay=0.0)
        assert cfg.initial_delay == 0.0

    def test_backoff_factor_exactly_one_is_valid(self) -> None:
        cfg = RetryConfig(backoff_factor=1.0)
        assert cfg.backoff_factor == 1.0


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------


class TestGlobalRetryConfig:
    """Tests for get_retry_config / set_retry_config."""

    def setup_method(self) -> None:
        # Reset to a known state before each test
        set_retry_config(RetryConfig())

    def teardown_method(self) -> None:
        # Always restore defaults so other tests are unaffected
        set_retry_config(RetryConfig())

    def test_get_returns_default(self) -> None:
        cfg = get_retry_config()
        assert cfg.max_attempts == 5

    def test_set_replaces_global(self) -> None:
        new_cfg = RetryConfig(max_attempts=10)
        set_retry_config(new_cfg)
        assert get_retry_config() is new_cfg

    def test_set_wrong_type_raises(self) -> None:
        with pytest.raises(TypeError):
            set_retry_config("not a config")  # type: ignore[arg-type]

    def test_set_and_get_roundtrip(self) -> None:
        cfg = RetryConfig(max_attempts=7, initial_delay=0.1, backoff_factor=1.5)
        set_retry_config(cfg)
        assert get_retry_config().max_attempts == 7
        assert get_retry_config().initial_delay == 0.1
        assert get_retry_config().backoff_factor == 1.5


# ---------------------------------------------------------------------------
# call_with_retry
# ---------------------------------------------------------------------------


class TestCallWithRetry:
    """Tests for the call_with_retry helper."""

    def setup_method(self) -> None:
        # Use a fast config (no real sleeping) for all tests
        set_retry_config(
            RetryConfig(max_attempts=3, initial_delay=0.0, backoff_factor=1.0)
        )

    def teardown_method(self) -> None:
        set_retry_config(RetryConfig())

    # --- success path ---

    def test_succeeds_on_first_attempt(self) -> None:
        fn = MagicMock(return_value="ok")
        result = call_with_retry(fn)
        assert result == "ok"
        fn.assert_called_once()

    def test_returns_value_from_fn(self) -> None:
        fn = MagicMock(return_value=42)
        assert call_with_retry(fn) == 42

    # --- retry path ---

    def test_retries_on_exception_then_succeeds(self) -> None:
        fn = MagicMock(side_effect=[RuntimeError("boom"), RuntimeError("boom"), "ok"])
        result = call_with_retry(fn)
        assert result == "ok"
        assert fn.call_count == 3

    def test_raises_after_all_attempts_exhausted(self) -> None:
        fn = MagicMock(side_effect=RuntimeError("persistent"))
        with pytest.raises(RuntimeError, match="persistent"):
            call_with_retry(fn)
        assert fn.call_count == 3

    def test_respects_max_attempts_one_no_retry(self) -> None:
        set_retry_config(
            RetryConfig(max_attempts=1, initial_delay=0.0, backoff_factor=1.0)
        )
        fn = MagicMock(side_effect=ValueError("fail"))
        with pytest.raises(ValueError):
            call_with_retry(fn)
        fn.assert_called_once()

    # --- selective exception matching ---

    def test_only_retries_configured_exception_types(self) -> None:
        set_retry_config(
            RetryConfig(
                max_attempts=3,
                initial_delay=0.0,
                backoff_factor=1.0,
                exceptions=(ValueError,),
            )
        )
        fn = MagicMock(side_effect=TypeError("wrong type"))
        with pytest.raises(TypeError):
            call_with_retry(fn)
        # Should NOT retry – TypeError is not in the configured exceptions
        fn.assert_called_once()

    def test_retries_on_matching_exception_type(self) -> None:
        set_retry_config(
            RetryConfig(
                max_attempts=3,
                initial_delay=0.0,
                backoff_factor=1.0,
                exceptions=(ValueError,),
            )
        )
        fn = MagicMock(side_effect=[ValueError("retry"), "ok"])
        result = call_with_retry(fn)
        assert result == "ok"
        assert fn.call_count == 2

    # --- back-off delay ---

    @patch("memiris.llm.retry_config.time.sleep")
    def test_sleeps_between_retries(self, mock_sleep: MagicMock) -> None:
        set_retry_config(
            RetryConfig(max_attempts=3, initial_delay=1.0, backoff_factor=2.0)
        )
        fn = MagicMock(side_effect=[RuntimeError(), RuntimeError(), "ok"])
        call_with_retry(fn)
        # First retry sleeps 1.0 s, second retry sleeps 2.0 s
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(1.0)
        mock_sleep.assert_any_call(2.0)

    @patch("memiris.llm.retry_config.time.sleep")
    def test_no_sleep_on_first_success(self, mock_sleep: MagicMock) -> None:
        fn = MagicMock(return_value="ok")
        call_with_retry(fn)
        mock_sleep.assert_not_called()

    @patch("memiris.llm.retry_config.time.sleep")
    def test_no_sleep_after_last_failed_attempt(self, mock_sleep: MagicMock) -> None:
        """The helper must not sleep after the final exhausted attempt."""
        set_retry_config(
            RetryConfig(max_attempts=2, initial_delay=1.0, backoff_factor=2.0)
        )
        fn = MagicMock(side_effect=RuntimeError("fail"))
        with pytest.raises(RuntimeError):
            call_with_retry(fn)
        # Only 1 sleep between attempt 1 and attempt 2; none after the final failure
        assert mock_sleep.call_count == 1
