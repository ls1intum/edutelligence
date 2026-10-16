"""Reasoning continuity in the tool loop and handling of incomplete responses."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.pyris_message import (  # noqa: E402
    IrisMessageRole,
    PyrisAIMessage,
    PyrisMessage,
    PyrisToolMessage,
)
from iris.common.token_usage_dto import TokenUsageDTO  # noqa: E402
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.domain.data.tool_message_content_dto import ToolMessageContentDTO
from iris.llm import CompletionArguments  # noqa: E402
from iris.llm.agent import AgentLoop, AgentTool  # noqa: E402
from iris.llm.errors import IncompleteModelResponse  # noqa: E402
from iris.llm.external.openai_chat import (  # noqa: E402
    DirectOpenAIChatModel,
    convert_responses_to_iris_message,
    convert_to_open_ai_messages,
    convert_to_responses_input,
)
from iris.llm.iris_chat_model import IrisChatModel  # noqa: E402

REASONING = {
    "type": "reasoning",
    "id": "rs_1",
    "encrypted_content": "gAAAA",
    "summary": [],
}
PREAMBLE = {
    "type": "message",
    "role": "assistant",
    "content": [{"type": "output_text", "text": "Let me check."}],
}
CALL = {
    "type": "function_call",
    "call_id": "call_1",
    "name": "lookup",
    "arguments": '{"query": "heaps"}',
    "status": "completed",
}


def _user(text):
    return PyrisMessage(
        sender=IrisMessageRole.USER, contents=[TextMessageContentDTO(textContent=text)]
    )


def _tool_turn(provider_items=None, reasoning_content=None):
    return PyrisAIMessage(
        contents=[TextMessageContentDTO(textContent="Let me check.")],
        toolCalls=[
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "lookup", "arguments": '{"query": "heaps"}'},
            }
        ],
        provider_items=provider_items,
        reasoning_content=reasoning_content,
    )


def _tool_result():
    return PyrisToolMessage(
        contents=[
            ToolMessageContentDTO(
                toolContent="heap facts", toolName="lookup", toolCallId="call_1"
            )
        ]
    )


def test_replay_sends_the_original_items_once_in_order():
    messages = [_user("q"), _tool_turn([REASONING, PREAMBLE, CALL]), _tool_result()]

    items = convert_to_responses_input(messages, replay_provider_items=True)

    assert items[0] == {"role": "user", "content": "q"}
    assert items[1:4] == [REASONING, PREAMBLE, CALL]
    assert items[4] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": "heap facts",
    }
    assert len(items) == 5


def test_without_replay_the_turn_is_rebuilt_from_text_and_calls():
    messages = [_user("q"), _tool_turn([REASONING, PREAMBLE, CALL]), _tool_result()]

    items = convert_to_responses_input(messages, replay_provider_items=False)

    assert all(item.get("type") != "reasoning" for item in items)
    assert [item.get("type") for item in items[2:]] == [
        "function_call",
        "function_call_output",
    ]


def test_provider_items_are_not_serialized_for_artemis():
    dumped = _tool_turn([REASONING], reasoning_content="think").model_dump(
        by_alias=True
    )

    assert "provider_items" not in dumped and "providerItems" not in dumped
    assert "reasoning_content" not in dumped


def _response(status, output, incomplete_reason=None):
    return SimpleNamespace(
        status=status,
        output=output,
        output_text="",
        error=None,
        incomplete_details=SimpleNamespace(reason=incomplete_reason),
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=5,
            input_tokens_details=SimpleNamespace(cached_tokens=0),
        ),
    )


def _item(**fields):
    return SimpleNamespace(**fields)


def test_completed_tool_call_response_keeps_its_items():
    response = _response(
        "completed",
        [
            _item(type="reasoning", id="rs_1", encrypted_content="gAAAA"),
            _item(
                type="function_call",
                call_id="call_1",
                name="lookup",
                arguments="{}",
                status="completed",
            ),
        ],
    )

    message = convert_responses_to_iris_message(response, "luna", keep_items=True)

    assert isinstance(message, PyrisAIMessage)
    assert [item["type"] for item in message.provider_items] == [
        "reasoning",
        "function_call",
    ]
    assert message.provider_items[0]["encrypted_content"] == "gAAAA"


def test_incomplete_response_with_tool_calls_is_rejected_with_its_usage():
    response = _response(
        "incomplete",
        [
            _item(
                type="function_call",
                call_id="c",
                name="lookup",
                arguments='{"q',
                status="incomplete",
            )
        ],
        incomplete_reason="max_output_tokens",
    )

    with pytest.raises(IncompleteModelResponse) as raised:
        convert_responses_to_iris_message(response, "luna", keep_items=True)

    assert raised.value.token_usage.num_input_tokens == 10


def test_truncation_during_reasoning_without_text_is_an_empty_answer_not_a_tool_run():
    response = _response(
        "incomplete",
        [_item(type="reasoning", id="rs_1", encrypted_content="gAAAA")],
        incomplete_reason="max_output_tokens",
    )

    message = convert_responses_to_iris_message(response, "luna", keep_items=True)

    assert not isinstance(message, PyrisAIMessage)
    assert message.contents[0].text_content == ""


def test_a_completed_call_then_an_incomplete_call_fails_the_run_and_keeps_both_usages():
    calls = []
    responses = [
        _tool_turn([REASONING, CALL]),
        IncompleteModelResponse("cut", TokenUsageDTO(numInputTokens=7)),
    ]

    class _Handler:
        model_id = "luna"

        def chat(self, messages, arguments, tools):
            del arguments, tools
            calls.append(list(messages))
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

    tool_runs = []

    def lookup(query: str) -> str:
        """Look up."""
        tool_runs.append(query)
        return "heap facts"

    model = IrisChatModel(_Handler())
    usages = []
    loop = AgentLoop(
        model=model,
        tools=[AgentTool.from_function(lookup)],
        on_model_call=lambda: usages.append(model.tokens),
    )

    with pytest.raises(IncompleteModelResponse):
        loop.run([_user("q")])

    assert tool_runs == ["heaps"]
    assert len(usages) == 2 and usages[1].num_input_tokens == 7
    # The second request replays the first turn with its reasoning item.
    assert calls[1][1].provider_items == [REASONING, CALL]


def test_responses_request_asks_for_encrypted_reasoning_when_replay_is_on():
    model = DirectOpenAIChatModel(
        id="luna",
        type="openai_chat",
        model="gpt-6-luna",
        api_key="sk-test",  # pragma: allowlist secret
        use_responses_api=True,
    )
    client = MagicMock()
    client.responses.create.return_value = _response(
        "completed",
        [_item(type="message", content=[_item(type="output_text", text="hi")])],
    )

    with patch.object(DirectOpenAIChatModel, "get_client", lambda self: client):
        model.chat([_user("q")], CompletionArguments(), tools=None)

    params = client.responses.create.call_args.kwargs
    assert params["include"] == ["reasoning.encrypted_content"]
    assert params["store"] is False


def test_chat_completions_reasoning_content_is_sent_back_only_when_enabled():
    messages = [_user("q"), _tool_turn(reasoning_content="I should look it up.")]

    default = convert_to_open_ai_messages(messages)
    enabled = convert_to_open_ai_messages(messages, replay_reasoning_content=True)

    assert "reasoning_content" not in default[1]
    assert enabled[1]["reasoning_content"] == "I should look it up."
