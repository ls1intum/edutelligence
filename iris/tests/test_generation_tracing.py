"""Model calls are Langfuse generations with the model name and token counts."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.token_usage_dto import TokenUsageDTO  # noqa: E402
from iris.llm.errors import IncompleteModelResponse  # noqa: E402
from iris.llm.external.openai_chat import OpenAIChatModel  # noqa: E402
from iris.tracing.langfuse_tracer import record_generation  # noqa: E402

TRACER = "iris.tracing.langfuse_tracer"


def _usage(input_tokens=120, output_tokens=30):
    return TokenUsageDTO(
        model="m", numInputTokens=input_tokens, numOutputTokens=output_tokens
    )


def test_the_generation_gets_the_model_and_the_token_counts():
    client = Mock()
    with (
        patch(f"{TRACER}._is_enabled", return_value=True),
        patch(f"{TRACER}.get_langfuse_client", return_value=client),
    ):
        record_generation("gpt-x", _usage())

    client.update_current_generation.assert_called_once_with(
        model="gpt-x", usage_details={"input": 120, "output": 30}
    )


def test_a_call_without_usage_records_only_the_model():
    client = Mock()
    with (
        patch(f"{TRACER}._is_enabled", return_value=True),
        patch(f"{TRACER}.get_langfuse_client", return_value=client),
    ):
        record_generation("gpt-x", None)

    client.update_current_generation.assert_called_once_with(
        model="gpt-x", usage_details=None
    )


def test_nothing_is_recorded_when_tracing_is_off():
    client = Mock()
    with (
        patch(f"{TRACER}._is_enabled", return_value=False),
        patch(f"{TRACER}.get_langfuse_client", return_value=client),
    ):
        record_generation("gpt-x", _usage())

    client.update_current_generation.assert_not_called()


def test_a_tracing_error_does_not_reach_the_caller():
    client = Mock()
    client.update_current_generation.side_effect = RuntimeError("no span")
    with (
        patch(f"{TRACER}._is_enabled", return_value=True),
        patch(f"{TRACER}.get_langfuse_client", return_value=client),
    ):
        record_generation("gpt-x", _usage())


def _model(chat):
    return SimpleNamespace(model="gpt-x", _chat=chat)


def test_openai_chat_records_the_usage_of_its_response():
    response = SimpleNamespace(token_usage=_usage(output_tokens=7))
    with patch("iris.llm.external.openai_chat.record_generation") as record:
        result = OpenAIChatModel.chat(
            _model(lambda *_args: response), [], SimpleNamespace(), None
        )

    assert result is response
    record.assert_called_once_with("gpt-x", response.token_usage)


def test_openai_chat_records_the_usage_of_a_cut_response():
    usage = _usage(output_tokens=600)

    def cut(*_args):
        raise IncompleteModelResponse("stopped", usage)

    with patch("iris.llm.external.openai_chat.record_generation") as record:
        with pytest.raises(IncompleteModelResponse):
            OpenAIChatModel.chat(_model(cut), [], SimpleNamespace(), None)

    record.assert_called_once_with("gpt-x", usage)
