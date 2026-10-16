"""Each chat LLM call is billed once, with its pipeline, and the prompt keeps a stable prefix."""

# pylint: skip-file

from types import SimpleNamespace
from unittest.mock import MagicMock

# Bootstrap the iris package (see test_chat_latency_ordering.py for the circular import).
import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.callback_token import CallbackToken
from iris.common.pipeline_enum import PipelineEnum  # noqa: E402
from iris.common.pyris_message import (  # noqa: E402
    IrisMessageRole,
    PyrisAIMessage,
    PyrisMessage,
)
from iris.common.token_usage_dto import TokenUsageDTO  # noqa: E402
from iris.domain.data.text_message_content_dto import (  # noqa: E402
    TextMessageContentDTO,
)
from iris.pipeline.chat.chat_pipeline import ChatPipeline  # noqa: E402
from iris.pipeline.chat.iris_chat_mode import IrisChatMode  # noqa: E402
from iris.web.status.status_update import ChatRunCallback  # noqa: E402


def _callback_with_outbox(results=None):
    callback = ChatRunCallback(
        run_id="run-1",
        base_url="http://artemis",
        auth_token=CallbackToken("token-for-run-1"),
    )
    outbox: list[dict] = []
    results = list(results or [])

    def send(payload, **_kwargs):
        outbox.append(payload)
        return results.pop(0) if results else True

    callback._send_status_payload = send
    return callback, outbox


def _input_counts(payload):
    return [token["numInputTokens"] for token in payload["tokens"]]


def test_finish_sends_only_usage_not_sent_with_the_result():
    answer = TokenUsageDTO(numInputTokens=100)
    title = TokenUsageDTO(numInputTokens=7)
    callback, outbox = _callback_with_outbox()

    callback.send_result("answer", tokens=[answer])
    callback.finish(tokens=[answer, title])

    assert _input_counts(outbox[0]) == [100]
    assert _input_counts(outbox[1]) == [7]


def test_fail_sends_only_usage_not_sent_before():
    answer = TokenUsageDTO(numInputTokens=100)
    title = TokenUsageDTO(numInputTokens=7)
    callback, outbox = _callback_with_outbox()

    callback.send_result("answer", tokens=[answer])
    callback.fail("suggestions down", tokens=[answer, title])

    assert _input_counts(outbox[1]) == [7]


def test_equal_but_separate_usages_are_both_sent():
    first = TokenUsageDTO(numInputTokens=5)
    second = TokenUsageDTO(numInputTokens=5)
    callback, outbox = _callback_with_outbox()

    callback.send_result("answer", tokens=[first])
    callback.finish(tokens=[first, second])

    assert _input_counts(outbox[1]) == [5]


class _ScriptedModel:
    """Answers with prebuilt responses; each sets the usage the call reported."""

    def __init__(self, script):
        self.script = list(script)
        self.tokens = None
        self.request_handler = SimpleNamespace(model_id="test-model")

    def chat(self, messages, tools=None, tool_choice=None):
        response, usage = self.script.pop(0)
        self.tokens = usage
        return response


def _tool_call_turn():
    return PyrisAIMessage(
        contents=[TextMessageContentDTO(textContent="")],
        toolCalls=[
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "lookup", "arguments": "{}"},
            }
        ],
    )


def _answer(text="done"):
    return PyrisMessage(
        sender=IrisMessageRole.ASSISTANT,
        contents=[TextMessageContentDTO(textContent=text)],
    )


def lookup() -> str:
    """Look something up."""
    return "result"


def _agent_state(llm):
    return SimpleNamespace(
        llm=llm,
        tokens=[],
        callback=MagicMock(),
        activity_tracker=MagicMock(),
        tracing_context=None,
        tools=[lookup],
        prompt_messages=[_answer("system")],
    )


def _pipeline(chat_mode: IrisChatMode) -> ChatPipeline:
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline.chat_mode = chat_mode
    return pipeline


def test_agent_records_each_llm_call_once_with_the_chat_pipeline():
    first, second = TokenUsageDTO(numInputTokens=10), TokenUsageDTO(numInputTokens=20)
    # The second call reports the same usage object again (as a client that did
    # not replace it would); it must not be billed twice.
    llm = _ScriptedModel(
        [(_tool_call_turn(), first), (_tool_call_turn(), first), (_answer(), second)]
    )
    state = _agent_state(llm)

    assert _pipeline(IrisChatMode.COURSE)._run_agent_loop(state) == "done"

    assert len(state.tokens) == 2
    assert state.tokens[0] is first and state.tokens[1] is second
    assert {token.pipeline for token in state.tokens} == {
        PipelineEnum.IRIS_CHAT_COURSE_MESSAGE
    }


def test_agent_labels_exercise_and_lecture_chat_tokens():
    for mode, expected in [
        (IrisChatMode.EXERCISE, PipelineEnum.IRIS_CHAT_EXERCISE_MESSAGE),
        (IrisChatMode.TEXT_EXERCISE, PipelineEnum.IRIS_CHAT_EXERCISE_MESSAGE),
        (IrisChatMode.LECTURE, PipelineEnum.IRIS_CHAT_LECTURE_MESSAGE),
    ]:
        usage = TokenUsageDTO(numInputTokens=1)
        state = _agent_state(_ScriptedModel([(_answer(), usage)]))

        _pipeline(mode)._run_agent_loop(state)

        assert state.tokens[0].pipeline == expected


def test_turn_context_follows_the_history():
    pipeline = _pipeline(IrisChatMode.COURSE)
    state = SimpleNamespace(
        message_history=[
            PyrisMessage(
                sender=IrisMessageRole.USER,
                contents=[TextMessageContentDTO(textContent="What is {a} heap?")],
            )
        ]
    )

    messages = pipeline.build_prompt_messages(
        state, system_prompt="Static {prompt}", turn_context="Date: {today}"
    )

    assert [message.sender for message in messages] == [
        IrisMessageRole.SYSTEM,
        IrisMessageRole.USER,
        IrisMessageRole.SYSTEM,
    ]
    assert messages[0].contents[0].text_content == "Static {prompt}"
    assert messages[1].contents[0].text_content == "What is {a} heap?"
    assert messages[2].contents[0].text_content == "Date: {today}"


def test_no_turn_context_keeps_the_previous_layout():
    pipeline = _pipeline(IrisChatMode.COURSE)
    state = SimpleNamespace(message_history=[])

    assert len(pipeline.build_prompt_messages(state, system_prompt="Static")) == 1


def test_mcq_intro_usage_is_billed_once_with_the_chat_pipeline():
    usage = TokenUsageDTO(numInputTokens=40, numCachedInputTokens=32)
    llm = MagicMock()
    llm.tokens = None

    def chat(_messages, tools=None, tool_choice=None):
        assert tools is None
        llm.tokens = usage
        return _answer("Sure, here is a quiz!")

    llm.chat.side_effect = chat
    state = _agent_state(llm)
    state.mcq_parallel = True

    for mode, expected in [
        (IrisChatMode.COURSE, PipelineEnum.IRIS_CHAT_COURSE_MESSAGE),
        (IrisChatMode.LECTURE, PipelineEnum.IRIS_CHAT_LECTURE_MESSAGE),
    ]:
        state.tokens = []
        llm.tokens = None

        assert _pipeline(mode).execute_agent(state) == "Sure, here is a quiz!"

        assert state.tokens == [usage]
        assert state.tokens[0].pipeline == expected
        assert state.tokens[0].num_cached_input_tokens == 32
