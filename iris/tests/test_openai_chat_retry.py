from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import openai
import pytest

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.llm import CompletionArguments  # noqa: E402
from iris.llm.external.openai_chat import DirectOpenAIChatModel  # noqa: E402


def _mock_openai_response():
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(
                    role="assistant",
                    content="ok",
                    tool_calls=None,
                    refusal=None,
                ),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
    )


def _build_model():
    return DirectOpenAIChatModel(
        id="test-model",
        type="openai_chat",
        model="gpt-test",
        api_key="sk-test",  # pragma: allowlist secret
    )


def _http_response(status_code: int) -> httpx.Response:
    return httpx.Response(
        status_code,
        request=httpx.Request("POST", "https://example.com/v1/chat/completions"),
    )


def test_bad_request_is_not_retried():
    model = _build_model()
    mock_client = MagicMock()
    error = openai.BadRequestError(
        "bad request",
        response=_http_response(400),
        body=None,
    )
    mock_client.chat.completions.create.side_effect = error

    with (
        patch.object(DirectOpenAIChatModel, "get_client", lambda self: mock_client),
        patch("time.sleep") as sleep,
        pytest.raises(openai.BadRequestError),
    ):
        model.chat([], CompletionArguments(), tools=None)

    assert mock_client.chat.completions.create.call_count == 1
    sleep.assert_not_called()


def test_rate_limit_retries_until_success():
    model = _build_model()
    mock_client = MagicMock()
    rate_limit_error = openai.RateLimitError(
        "rate limited",
        response=_http_response(429),
        body=None,
    )
    mock_client.chat.completions.create.side_effect = [
        rate_limit_error,
        rate_limit_error,
        _mock_openai_response(),
    ]

    with (
        patch.object(DirectOpenAIChatModel, "get_client", lambda self: mock_client),
        patch("time.sleep") as sleep,
    ):
        result = model.chat([], CompletionArguments(), tools=None)

    assert result.contents[0].text_content == "ok"
    assert mock_client.chat.completions.create.call_count == 3
    assert sleep.call_count == 2


def test_internal_server_error_retries_until_success():
    model = _build_model()
    mock_client = MagicMock()
    server_error = openai.InternalServerError(
        "server error",
        response=_http_response(503),
        body=None,
    )
    mock_client.chat.completions.create.side_effect = [
        server_error,
        _mock_openai_response(),
    ]

    with (
        patch.object(DirectOpenAIChatModel, "get_client", lambda self: mock_client),
        patch("time.sleep") as sleep,
    ):
        result = model.chat([], CompletionArguments(), tools=None)

    assert result.contents[0].text_content == "ok"
    assert mock_client.chat.completions.create.call_count == 2
    sleep.assert_called_once()


def test_request_timeout_408_is_retried():
    model = _build_model()
    mock_client = MagicMock()
    timeout_error = openai.APIStatusError(
        "request timeout",
        response=_http_response(408),
        body=None,
    )
    mock_client.chat.completions.create.side_effect = [
        timeout_error,
        _mock_openai_response(),
    ]

    with (
        patch.object(DirectOpenAIChatModel, "get_client", lambda self: mock_client),
        patch("time.sleep") as sleep,
    ):
        result = model.chat([], CompletionArguments(), tools=None)

    assert result.contents[0].text_content == "ok"
    assert mock_client.chat.completions.create.call_count == 2
    sleep.assert_called_once()


def test_conflict_409_is_retried():
    model = _build_model()
    mock_client = MagicMock()
    conflict_error = openai.ConflictError(
        "lock timeout",
        response=_http_response(409),
        body=None,
    )
    mock_client.chat.completions.create.side_effect = [
        conflict_error,
        _mock_openai_response(),
    ]

    with (
        patch.object(DirectOpenAIChatModel, "get_client", lambda self: mock_client),
        patch("time.sleep") as sleep,
    ):
        result = model.chat([], CompletionArguments(), tools=None)

    assert result.contents[0].text_content == "ok"
    assert mock_client.chat.completions.create.call_count == 2
    sleep.assert_called_once()


def test_qa_single_attempt_does_not_sleep_after_final_retryable_error(monkeypatch):
    monkeypatch.setenv("IRIS_QA_OPENAI_RETRIES", "1")
    model = _build_model()
    mock_client = MagicMock()
    error = openai.RateLimitError(
        "rate limited",
        response=_http_response(429),
        body=None,
    )
    mock_client.chat.completions.create.side_effect = error

    with (
        patch.object(DirectOpenAIChatModel, "get_client", lambda self: mock_client),
        patch("time.sleep") as sleep,
        pytest.raises(openai.RateLimitError),
    ):
        model.chat([], CompletionArguments(), tools=None)

    assert mock_client.chat.completions.create.call_count == 1
    sleep.assert_not_called()
