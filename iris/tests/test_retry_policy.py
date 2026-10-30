"""The retry policy for model API calls: what is retried, how long it waits."""

import threading
from unittest.mock import MagicMock, patch

import httpx
import openai
import pytest

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.llm import CompletionArguments, retry  # noqa: E402
from iris.llm.external.openai_chat import DirectOpenAIChatModel  # noqa: E402
from iris.llm.retry import RetryState, backoff_seconds, retry_after_seconds


def _response(status_code: int, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code,
        headers=headers or {},
        request=httpx.Request("POST", "https://example.com/v1/chat/completions"),
    )


def _rate_limit(headers: dict | None = None) -> openai.RateLimitError:
    return openai.RateLimitError(
        "slow down", response=_response(429, headers), body=None
    )


def _timeout() -> openai.APITimeoutError:
    return openai.APITimeoutError(
        request=httpx.Request("POST", "https://example.com/v1/chat/completions")
    )


def test_retry_after_ms_header_wins_over_retry_after():
    error = _rate_limit({"retry-after-ms": "1500", "retry-after": "9"})
    assert retry_after_seconds(error) == pytest.approx(1.5)


def test_retry_after_seconds_header():
    assert retry_after_seconds(_rate_limit({"retry-after": "3"})) == 3.0


def test_missing_retry_headers():
    assert retry_after_seconds(_rate_limit()) is None


def test_backoff_has_jitter_within_the_exponential_ceiling():
    for attempt in range(6):
        ceiling = min(retry.MAX_BACKOFF_SECONDS, 2.0**attempt)
        value = backoff_seconds(attempt)
        assert ceiling / 2 <= value <= ceiling


def test_bad_request_is_never_retried():
    error = openai.BadRequestError("bad", response=_response(400), body=None)
    assert RetryState().should_retry(error, 0) is False


def test_no_retry_after_the_last_attempt():
    state = RetryState(max_attempts=3)
    assert state.should_retry(_rate_limit(), 1) is True
    assert state.should_retry(_rate_limit(), 2) is False


def test_a_timed_out_request_is_retried_only_once():
    state = RetryState()
    assert state.should_retry(_timeout(), 0) is True
    assert state.should_retry(_timeout(), 1) is False


def test_server_asking_for_a_very_long_pause_is_not_retried():
    error = _rate_limit({"retry-after": str(retry.MAX_WAIT_SECONDS + 60)})
    assert RetryState().should_retry(error, 0) is False


def test_cancelled_run_is_not_retried_and_wait_returns_at_once():
    cancel = threading.Event()
    cancel.set()
    state = RetryState(cancel_event=cancel)
    assert state.should_retry(_rate_limit(), 0) is False
    with patch("time.sleep") as sleep:
        state.wait(_rate_limit({"retry-after": "20"}), 0)
    sleep.assert_not_called()


def test_wait_uses_the_server_requested_pause():
    with patch("time.sleep") as sleep:
        RetryState().wait(_rate_limit({"retry-after-ms": "250"}), 0)
    sleep.assert_called_once_with(pytest.approx(0.25))


def test_chat_raises_the_last_error_without_a_final_sleep():
    model = DirectOpenAIChatModel(
        id="test-model",
        type="openai_chat",
        model="gpt-test",
        api_key="sk-test",  # pragma: allowlist secret
    )
    client = MagicMock()
    client.chat.completions.create.side_effect = _rate_limit()
    with (
        patch.object(DirectOpenAIChatModel, "get_client", lambda self: client),
        patch("time.sleep") as sleep,
        pytest.raises(openai.RateLimitError),
    ):
        model.chat([], CompletionArguments(), tools=None)
    assert client.chat.completions.create.call_count == retry.MAX_ATTEMPTS
    # One pause between attempts, none after the last one.
    assert sleep.call_count == retry.MAX_ATTEMPTS - 1
