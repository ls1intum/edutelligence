from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

# Bootstrap the iris package: importing iris.llm directly hits a pre-existing
# circular import between iris.common.pyris_message and iris.domain. Loading
# iris.pipeline.pipeline first establishes the right module init order — this
# mirrors what every working pipeline test already does transitively.
import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.llm import CompletionArguments  # noqa: E402
from iris.llm.external.openai_chat import DirectOpenAIChatModel  # noqa: E402


def _mock_openai_response():
    """Build a minimal chat-completion response object."""
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


def _mock_responses_response():
    """Build a minimal Responses-API response object."""
    return SimpleNamespace(
        status="completed",
        output=[
            SimpleNamespace(
                type="message",
                content=[SimpleNamespace(type="output_text", text="ok")],
            )
        ],
        output_text="ok",
        usage=SimpleNamespace(
            input_tokens=1,
            output_tokens=1,
            output_tokens_details=SimpleNamespace(reasoning_tokens=0),
        ),
    )


def _build_model(**overrides):
    base = {
        "id": "test-model",
        "type": "openai_chat",
        "model": "gpt-test",
        "api_key": "sk-test",  # pragma: allowlist secret
    }
    base.update(overrides)
    return DirectOpenAIChatModel(**base)


def _invoke_chat(model, **completion_kwargs):
    """Invoke the chat-completions path and return the request kwargs."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_openai_response()
    with patch.object(DirectOpenAIChatModel, "get_client", lambda self: mock_client):
        model.chat([], CompletionArguments(**completion_kwargs), tools=None)
    return mock_client.chat.completions.create.call_args.kwargs


def _invoke_responses(model, **completion_kwargs):
    """Invoke the Responses path and return the request kwargs."""
    mock_client = MagicMock()
    mock_client.responses.create.return_value = _mock_responses_response()
    with patch.object(DirectOpenAIChatModel, "get_client", lambda self: mock_client):
        model.chat([], CompletionArguments(**completion_kwargs), tools=None)
    return mock_client.responses.create.call_args.kwargs


def test_allowance_extends_chat_completion_budget():
    # SessionTitleGenerationPipeline requests max_tokens=30; a model with a
    # 4096-token allowance must get 30 + 4096 so reasoning cannot eat the whole
    # budget before the title is emitted.
    model = _build_model(reasoning_token_allowance=4096)
    params = _invoke_chat(model, max_tokens=30)
    assert params["max_completion_tokens"] == 4126


def test_allowance_extends_responses_budget():
    model = _build_model(use_responses_api=True, reasoning_token_allowance=4096)
    params = _invoke_responses(model, max_tokens=30)
    assert params["max_output_tokens"] == 4126


def test_without_allowance_the_requested_budget_is_unchanged():
    model = _build_model()  # allowance defaults to 0
    assert _invoke_chat(model, max_tokens=30)["max_completion_tokens"] == 30
    assert _invoke_responses(model, max_tokens=30)["max_output_tokens"] == 30


def test_allowance_must_not_be_negative():
    with pytest.raises(ValidationError):
        _build_model(reasoning_token_allowance=-1)
