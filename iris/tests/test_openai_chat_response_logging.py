from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.pyris_message import PyrisAIMessage
from iris.llm import CompletionArguments
from iris.llm.external.openai_chat import DirectOpenAIChatModel


def _build_model():
    return DirectOpenAIChatModel(
        id="test-model",
        type="openai_chat",
        model="gpt-test",
        api_key="sk-test",  # pragma: allowlist secret
    )


def _completion_response(*, content, finish_reason, tool_calls=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(
                    role="assistant",
                    content=content,
                    tool_calls=tool_calls,
                    refusal=None,
                ),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
    )


def _tool_call():
    return SimpleNamespace(
        id="call-1",
        type="function",
        function=SimpleNamespace(
            name="lookup_course",
            arguments='{"course": "computer science"}',
        ),
    )


@pytest.mark.parametrize("content", [None, ""])
def test_tool_call_response_is_not_logged_as_empty(caplog, content):
    model = _build_model()
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _completion_response(
        content=content,
        finish_reason="tool_calls",
        tool_calls=[_tool_call()],
    )

    with patch.object(DirectOpenAIChatModel, "get_client", lambda self: mock_client):
        result = model.chat([], CompletionArguments(), tools=None)

    assert isinstance(result, PyrisAIMessage)
    assert result.tool_calls is not None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call-1"
    assert result.tool_calls[0].function.name == "lookup_course"
    assert result.tool_calls[0].function.arguments == {"course": "computer science"}
    error_messages = [
        record.getMessage() for record in caplog.records if record.levelname == "ERROR"
    ]
    assert "Model returned an empty message" not in error_messages
    assert "Finish reason: tool_calls" not in error_messages


def test_genuinely_empty_response_is_logged(caplog):
    model = _build_model()
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _completion_response(
        content="",
        finish_reason="length",
    )

    with patch.object(DirectOpenAIChatModel, "get_client", lambda self: mock_client):
        result = model.chat([], CompletionArguments(), tools=None)

    assert not isinstance(result, PyrisAIMessage)
    error_messages = [
        record.getMessage() for record in caplog.records if record.levelname == "ERROR"
    ]
    assert "Model returned an empty message" in error_messages
    assert "Finish reason: length" in error_messages
