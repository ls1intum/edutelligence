"""Each chat LLM call is billed once, with its pipeline, and the prompt keeps a stable prefix."""

# pylint: skip-file

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402

# Bootstrap the iris package (see test_chat_latency_ordering.py for the circular import).
import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.pipeline_enum import PipelineEnum  # noqa: E402
from iris.common.pyris_message import IrisMessageRole, PyrisMessage  # noqa: E402
from iris.common.token_usage_dto import TokenUsageDTO  # noqa: E402
from iris.domain.data.text_message_content_dto import (  # noqa: E402
    TextMessageContentDTO,
)
from iris.pipeline.chat.chat_pipeline import ChatPipeline  # noqa: E402
from iris.pipeline.chat.iris_chat_mode import IrisChatMode  # noqa: E402
from iris.web.status.status_update import ChatRunCallback  # noqa: E402


def _callback_with_outbox(results=None):
    callback = ChatRunCallback(run_id="run-1", base_url="http://artemis")
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


def test_usage_of_an_undelivered_result_is_sent_with_finish():
    answer = TokenUsageDTO(numInputTokens=100)
    title = TokenUsageDTO(numInputTokens=7)
    callback, outbox = _callback_with_outbox(results=[False, False, False, True])

    with patch("iris.web.status.status_update.time.sleep"):
        callback.send_result("answer", tokens=[answer])
        callback.finish(tokens=[answer, title])

    assert _input_counts(outbox[-1]) == [100, 7]
    assert outbox[-1]["result"] == "answer"


def test_equal_but_separate_usages_are_both_sent():
    first = TokenUsageDTO(numInputTokens=5)
    second = TokenUsageDTO(numInputTokens=5)
    callback, outbox = _callback_with_outbox()

    callback.send_result("answer", tokens=[first])
    callback.finish(tokens=[first, second])

    assert _input_counts(outbox[1]) == [5]


class _FakeExecutor:
    """Yields agent steps; ``None`` means the step made no new LLM call."""

    def __init__(self, llm, step_usages):
        self.llm = llm
        self.step_usages = step_usages

    def iter(self, _params, callbacks=None):
        for index, usage in enumerate(self.step_usages):
            if usage is not None:
                self.llm.tokens = usage
            last = index == len(self.step_usages) - 1
            yield {"output": "done"} if last else {"intermediate_steps": []}


def _agent_state(llm):
    return SimpleNamespace(
        llm=llm,
        tokens=[],
        callback=MagicMock(),
        activity_tracker=MagicMock(),
        tracing_context=None,
    )


def _pipeline(chat_mode: IrisChatMode) -> ChatPipeline:
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline.chat_mode = chat_mode
    pipeline.on_agent_step = lambda state, step: None
    return pipeline


def test_agent_records_each_llm_call_once_with_the_chat_pipeline():
    first, second = TokenUsageDTO(numInputTokens=10), TokenUsageDTO(numInputTokens=20)
    llm = SimpleNamespace(tokens=None)
    state = _agent_state(llm)

    _pipeline(IrisChatMode.COURSE)._run_agent_iterations(
        state, _FakeExecutor(llm, [first, None, second]), {}
    )

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
        llm = SimpleNamespace(tokens=None)
        state = _agent_state(llm)

        _pipeline(mode)._run_agent_iterations(state, _FakeExecutor(llm, [usage]), {})

        assert state.tokens[0].pipeline == expected


def test_turn_context_follows_the_history_and_precedes_the_scratchpad():
    pipeline = _pipeline(IrisChatMode.COURSE)
    state = SimpleNamespace(
        message_history=[
            PyrisMessage(
                sender=IrisMessageRole.USER,
                contents=[TextMessageContentDTO(textContent="What is {a} heap?")],
            )
        ]
    )

    prompt = pipeline.assemble_prompt_with_history(
        state, system_prompt="Static {prompt}", turn_context="Date: {today}"
    )
    messages = prompt.format_messages(agent_scratchpad=[])

    assert [type(message) for message in messages] == [
        SystemMessage,
        HumanMessage,
        SystemMessage,
    ]
    assert messages[0].content == "Static {prompt}"
    assert messages[2].content == "Date: {today}"


def test_no_turn_context_keeps_the_previous_layout():
    pipeline = _pipeline(IrisChatMode.COURSE)
    state = SimpleNamespace(message_history=[])

    prompt = pipeline.assemble_prompt_with_history(state, system_prompt="Static")

    assert len(prompt.format_messages(agent_scratchpad=[])) == 1
