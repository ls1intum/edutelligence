"""IrisChatModel keeps per-call usage and final-answer logprobs like the old wrapper."""

import pytest

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.pipeline_enum import PipelineEnum  # noqa: E402
from iris.common.pyris_message import (  # noqa: E402
    IrisMessageRole,
    PyrisAIMessage,
    PyrisMessage,
)
from iris.common.token_usage_dto import TokenUsageDTO  # noqa: E402
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.llm import CompletionArguments  # noqa: E402
from iris.llm.iris_chat_model import IncompleteModelResponse, IrisChatModel


class _Handler:
    """A request handler returning scripted responses."""

    model_id = "luna"

    def __init__(self, responses):
        self.responses = list(responses)
        self.arguments = []

    def chat(self, messages, arguments, tools):
        del messages, tools
        self.arguments.append(arguments)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _text(text, logprobs=None, usage=None):
    return PyrisMessage(
        sender=IrisMessageRole.ASSISTANT,
        contents=[TextMessageContentDTO(textContent=text)],
        token_logprobs=logprobs,
        token_usage=usage or TokenUsageDTO(numInputTokens=1),
    )


def _tool_turn():
    return PyrisAIMessage(
        contents=[TextMessageContentDTO(textContent="")],
        toolCalls=[
            {
                "id": "c",
                "type": "function",
                "function": {"name": "t", "arguments": "{}"},
            }
        ],
        token_usage=TokenUsageDTO(numInputTokens=2),
    )


def test_final_answer_logprobs_survive_tool_turns_and_are_cleared_by_a_later_answer():
    model = IrisChatModel(
        _Handler([_text("first", [-0.1]), _tool_turn(), _text("second", None)])
    )

    model.chat([])
    assert model.last_token_logprobs == [-0.1]
    model.chat([])  # a tool-call turn has no text and keeps the values
    assert model.last_token_logprobs == [-0.1]
    model.chat([])  # a text answer without logprobs clears them
    assert model.last_token_logprobs is None


def test_each_call_gets_a_fresh_usage_object_without_pipeline():
    usage = TokenUsageDTO(
        numInputTokens=5, pipeline=PipelineEnum.IRIS_CHAT_COURSE_MESSAGE
    )
    model = IrisChatModel(_Handler([_text("a", usage=usage), _text("b", usage=usage)]))

    model.chat([])
    first = model.tokens
    model.chat([])

    assert first is not model.tokens
    assert first.pipeline == PipelineEnum.NOT_SET
    assert model.model_name == "luna"


def test_tool_choice_override_does_not_change_the_default_arguments():
    handler = _Handler([_text("a")])
    defaults = CompletionArguments(temperature=0.5)
    model = IrisChatModel(handler, defaults)

    model.chat([], tools=[{"type": "function"}], tool_choice="none")

    assert handler.arguments[0].tool_choice == "none"
    assert defaults.tool_choice is None


def test_incomplete_response_records_usage_and_resets_the_stream():
    resets = []
    usage = TokenUsageDTO(numInputTokens=9)
    model = IrisChatModel(
        _Handler([IncompleteModelResponse("cut off", usage)]),
        CompletionArguments(stream_handler=resets.append),
    )

    with pytest.raises(IncompleteModelResponse):
        model.chat([])

    assert model.tokens.num_input_tokens == 9
    assert resets == [None]
