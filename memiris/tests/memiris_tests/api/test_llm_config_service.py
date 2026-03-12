"""Tests for memiris.api.llm_config_service.LlmConfigService."""

from typing import Any

import pytest

from memiris.api.llm_config_service import LlmConfigService
from memiris.llm.retry_config import RetryConfig, get_retry_config, set_retry_config


@pytest.fixture(autouse=True)
def reset_retry_config() -> Any:
    """Restore the default retry config after every test."""
    yield
    set_retry_config(RetryConfig())


class TestLlmConfigServiceGetRetryConfig:
    """Tests for LlmConfigService.get_retry_config()."""

    def test_returns_current_config(self) -> None:
        cfg = RetryConfig(max_attempts=7)
        set_retry_config(cfg)
        assert LlmConfigService.get_retry_config() is cfg

    def test_returns_default_config_initially(self) -> None:
        result = LlmConfigService.get_retry_config()
        assert result.max_attempts == RetryConfig().max_attempts
        assert result.initial_delay == RetryConfig().initial_delay
        assert result.backoff_factor == RetryConfig().backoff_factor


class TestLlmConfigServiceConfigureRetry:
    """Tests for LlmConfigService.configure_retry()."""

    def test_replaces_global_config(self) -> None:
        new_cfg = RetryConfig(max_attempts=10, initial_delay=0.5, backoff_factor=3.0)
        LlmConfigService.configure_retry(new_cfg)
        assert get_retry_config() is new_cfg

    def test_get_returns_newly_set_config(self) -> None:
        new_cfg = RetryConfig(max_attempts=2)
        LlmConfigService.configure_retry(new_cfg)
        assert LlmConfigService.get_retry_config() is new_cfg

    def test_raises_on_wrong_type(self) -> None:
        with pytest.raises(TypeError):
            LlmConfigService.configure_retry("not a config")  # type: ignore[arg-type]


class TestLlmConfigServiceConfigureRetryParams:
    """Tests for LlmConfigService.configure_retry_params()."""

    def test_updates_max_attempts_only(self) -> None:
        LlmConfigService.configure_retry_params(max_attempts=9)
        cfg = LlmConfigService.get_retry_config()
        assert cfg.max_attempts == 9
        assert cfg.initial_delay == RetryConfig().initial_delay
        assert cfg.backoff_factor == RetryConfig().backoff_factor

    def test_updates_initial_delay_only(self) -> None:
        LlmConfigService.configure_retry_params(initial_delay=3.5)
        cfg = LlmConfigService.get_retry_config()
        assert cfg.initial_delay == 3.5
        assert cfg.max_attempts == RetryConfig().max_attempts

    def test_updates_backoff_factor_only(self) -> None:
        LlmConfigService.configure_retry_params(backoff_factor=4.0)
        cfg = LlmConfigService.get_retry_config()
        assert cfg.backoff_factor == 4.0
        assert cfg.max_attempts == RetryConfig().max_attempts

    def test_updates_exceptions_only(self) -> None:
        LlmConfigService.configure_retry_params(exceptions=(ValueError, RuntimeError))
        cfg = LlmConfigService.get_retry_config()
        assert cfg.exceptions == (ValueError, RuntimeError)
        assert cfg.max_attempts == RetryConfig().max_attempts

    def test_updates_all_params(self) -> None:
        LlmConfigService.configure_retry_params(
            max_attempts=4,
            initial_delay=0.2,
            backoff_factor=1.5,
            exceptions=(OSError,),
        )
        cfg = LlmConfigService.get_retry_config()
        assert cfg.max_attempts == 4
        assert cfg.initial_delay == 0.2
        assert cfg.backoff_factor == 1.5
        assert cfg.exceptions == (OSError,)

    def test_no_args_leaves_config_unchanged(self) -> None:
        original = LlmConfigService.get_retry_config()
        LlmConfigService.configure_retry_params()
        updated = LlmConfigService.get_retry_config()
        assert updated.max_attempts == original.max_attempts
        assert updated.initial_delay == original.initial_delay
        assert updated.backoff_factor == original.backoff_factor
        assert updated.exceptions == original.exceptions

    def test_preserves_previous_custom_values(self) -> None:
        LlmConfigService.configure_retry(RetryConfig(max_attempts=8, initial_delay=2.0))
        LlmConfigService.configure_retry_params(backoff_factor=3.0)
        cfg = LlmConfigService.get_retry_config()
        assert cfg.max_attempts == 8
        assert cfg.initial_delay == 2.0
        assert cfg.backoff_factor == 3.0

    def test_invalid_max_attempts_raises(self) -> None:
        with pytest.raises(ValueError, match="max_attempts"):
            LlmConfigService.configure_retry_params(max_attempts=0)

    def test_invalid_initial_delay_raises(self) -> None:
        with pytest.raises(ValueError, match="initial_delay"):
            LlmConfigService.configure_retry_params(initial_delay=-1.0)

    def test_invalid_backoff_factor_raises(self) -> None:
        with pytest.raises(ValueError, match="backoff_factor"):
            LlmConfigService.configure_retry_params(backoff_factor=0.5)


class TestLlmConfigServiceResetRetryConfig:
    """Tests for LlmConfigService.reset_retry_config()."""

    def test_reset_restores_defaults(self) -> None:
        LlmConfigService.configure_retry(
            RetryConfig(max_attempts=99, initial_delay=10.0)
        )
        LlmConfigService.reset_retry_config()
        cfg = LlmConfigService.get_retry_config()
        defaults = RetryConfig()
        assert cfg.max_attempts == defaults.max_attempts
        assert cfg.initial_delay == defaults.initial_delay
        assert cfg.backoff_factor == defaults.backoff_factor
        assert cfg.exceptions == defaults.exceptions

    def test_reset_after_partial_update(self) -> None:
        LlmConfigService.configure_retry_params(max_attempts=3)
        LlmConfigService.reset_retry_config()
        assert (
            LlmConfigService.get_retry_config().max_attempts
            == RetryConfig().max_attempts
        )
