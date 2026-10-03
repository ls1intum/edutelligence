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


class _FakeArtemis:
    """Mirrors AbstractIrisChatSessionService: a repeated answer is ignored with all its tokens."""

    def __init__(self):
        self.has_answer = False
        self.recorded: list[int] = []

    def handle(self, payload):
        if payload.get("result") is not None and payload.get("final") is not False:
            if self.has_answer:
                return
            self.has_answer = True
        self.recorded += [token["numInputTokens"] for token in payload["tokens"] or []]


def _callback_against(artemis, delivered):
    """``delivered`` scripts, per POST, (reaches Artemis, Iris sees success)."""
    callback = ChatRunCallback(run_id="run-1", base_url="http://artemis")
    script = list(delivered)

    def send(payload, **_kwargs):
        reaches, succeeds = script.pop(0) if script else (True, True)
        if reaches:
            artemis.handle(payload)
        return succeeds

    callback._send_status_payload = send
    return callback


def _run_lost_result(artemis, first_post_reaches: bool):
    answer = TokenUsageDTO(numInputTokens=100)
    title = TokenUsageDTO(numInputTokens=7)
    suggestion = TokenUsageDTO(numInputTokens=3)
    callback = _callback_against(
        artemis, [(first_post_reaches, False), (False, False), (False, False)]
    )
    with patch("iris.web.status.status_update.time.sleep"):
        callback.send_result("answer", tokens=[answer])
        callback.send_suggestions(["s"])
        callback.finish(tokens=[answer, title, suggestion])


def test_answer_stored_despite_lost_responses_is_billed_once_with_later_usage():
    artemis = _FakeArtemis()

    _run_lost_result(artemis, first_post_reaches=True)

    assert sorted(artemis.recorded) == [3, 7, 100]


def test_answer_that_never_arrived_is_resent_and_billed_once():
    artemis = _FakeArtemis()

    _run_lost_result(artemis, first_post_reaches=False)

    assert artemis.has_answer
    assert sorted(artemis.recorded) == [3, 7, 100]


def test_usage_appended_to_the_callers_list_is_not_lost_with_the_answer():
    artemis = _FakeArtemis()
    tokens = [TokenUsageDTO(numInputTokens=100)]
    callback = _callback_against(
        artemis, [(True, False), (False, False), (False, False)]
    )

    with patch("iris.web.status.status_update.time.sleep"):
        callback.send_result("answer", tokens=tokens)
        tokens.append(TokenUsageDTO(numInputTokens=7))
        tokens.append(TokenUsageDTO(numInputTokens=3))
        callback.send_suggestions(["s"])
        callback.finish(tokens=tokens)

    assert sorted(artemis.recorded) == [3, 7, 100]


def test_terminal_update_after_failed_resends_keeps_newer_usage_apart():
    artemis = _FakeArtemis()
    tokens = [TokenUsageDTO(numInputTokens=100)]
    lost = [(True, False)] + [(False, False)] * 5
    callback = _callback_against(artemis, lost)

    with patch("iris.web.status.status_update.time.sleep"):
        callback.send_result("answer", tokens=tokens)
        tokens.append(TokenUsageDTO(numInputTokens=7))
        callback.finish(tokens=tokens)

    assert sorted(artemis.recorded) == [7, 100]


def test_usage_only_update_is_not_retried():
    """A usage-only update that reached Artemis but lost its response is not sent again."""
    artemis = _FakeArtemis()
    tokens = [TokenUsageDTO(numInputTokens=100)]
    # send_result: stored, response lost; three resends lost; usage-only update
    # reaches Artemis but its response is lost; terminal update succeeds.
    script = [(True, False), (False, False), (False, False)]
    script += [(False, False)] * 3 + [(True, False)]
    callback = _callback_against(artemis, script)

    with patch("iris.web.status.status_update.time.sleep"):
        callback.send_result("answer", tokens=tokens)
        tokens.append(TokenUsageDTO(numInputTokens=7))
        callback.finish(tokens=tokens)

    assert sorted(artemis.recorded) == [7, 100]


def test_resent_answer_goes_alone_before_the_update_that_triggered_it():
    answer = TokenUsageDTO(numInputTokens=100)
    title = TokenUsageDTO(numInputTokens=7)
    callback, outbox = _callback_with_outbox(results=[False, False, False])

    with patch("iris.web.status.status_update.time.sleep"):
        callback.send_result("answer", tokens=[answer])
        callback.finish(tokens=[answer, title])

    resent, terminal = outbox[-2], outbox[-1]
    assert resent["result"] == "answer" and _input_counts(resent) == [100]
    assert terminal["result"] is None and _input_counts(terminal) == [7]


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


def test_mcq_intro_usage_is_billed_once_with_the_chat_pipeline():
    usage = TokenUsageDTO(numInputTokens=40, numCachedInputTokens=32)
    llm = MagicMock()
    llm.tokens = None

    def invoke(_messages):
        llm.tokens = usage
        return SimpleNamespace(content="Sure, here is a quiz!")

    llm.invoke.side_effect = invoke
    state = _agent_state(llm)
    state.mcq_parallel = True
    state.prompt = MagicMock()

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
