"""Auto-compaction: history split, trigger, request, tool output limits and delivery."""

# pylint: skip-file

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from langchain_core.tools import StructuredTool  # noqa: E402

# Bootstrap the iris package (see test_chat_latency_ordering.py for the circular import).
import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.pipeline_enum import PipelineEnum  # noqa: E402
from iris.common.pyris_message import IrisMessageRole, PyrisMessage  # noqa: E402
from iris.common.token_usage_dto import TokenUsageDTO  # noqa: E402
from iris.domain.data.compaction_dto import CompactionDTO  # noqa: E402
from iris.domain.data.json_message_content_dto import (  # noqa: E402
    JsonMessageContentDTO,
)
from iris.domain.data.text_message_content_dto import (  # noqa: E402
    TextMessageContentDTO,
)
from iris.llm import CompletionArguments  # noqa: E402
from iris.llm.external.openai_chat import DirectOpenAIChatModel  # noqa: E402
from iris.pipeline import abstract_agent_pipeline  # noqa: E402
from iris.pipeline.chat.chat_pipeline import ChatPipeline  # noqa: E402
from iris.pipeline.chat.iris_chat_mode import IrisChatMode  # noqa: E402
from iris.pipeline.shared.compaction import (  # noqa: E402
    TOOL_OUTPUT_OMITTED,
    CompactionSettings,
    ToolOutputBudget,
    compaction_boundary,
    fit_to_budget,
    should_compact,
    split_history,
)
from iris.web.status.status_update import ChatRunCallback  # noqa: E402


def _text(message_id, sender, text="hello"):
    return PyrisMessage(
        id=message_id,
        sender=sender,
        contents=[TextMessageContentDTO(textContent=text)],
    )


def _user(message_id, text="hello"):
    return _text(message_id, IrisMessageRole.USER, text)


def _answer(message_id, text="answer"):
    return _text(message_id, IrisMessageRole.ASSISTANT, text)


def _compaction(message_id, covers, summary):
    return PyrisMessage(
        id=message_id,
        sender=IrisMessageRole.SUMMARY,
        contents=[
            JsonMessageContentDTO(
                jsonContent={"summary": summary, "coversThroughMessageId": covers}
            )
        ],
    )


def _chat(turns):
    """turns user/answer pairs with ids 1, 2, 3, ..."""
    messages = []
    for turn in range(turns):
        messages.append(_user(2 * turn + 1, f"question {turn}"))
        messages.append(_answer(2 * turn + 2, f"answer {turn}"))
    return messages


# --- history split ---------------------------------------------------------


def test_split_uses_the_summary_that_covers_the_furthest_message():
    messages = _chat(3)
    # The later stored summary covers less: a late job must not move the cutoff back.
    messages.insert(4, _compaction(100, covers=4, summary="far"))
    messages.append(_compaction(101, covers=2, summary="near"))

    split = split_history(messages)

    assert split.summary == "far"
    assert [m.id for m in split.messages] == [5, 6]


def test_split_ignores_summaries_of_other_sessions_and_unreadable_ones():
    messages = _chat(2) + [
        _compaction(100, covers=999, summary="foreign"),
        PyrisMessage(
            id=101,
            sender=IrisMessageRole.SUMMARY,
            contents=[JsonMessageContentDTO(jsonContent={"text": "bad"})],
        ),
    ]

    split = split_history(messages)

    assert split.summary is None
    assert [m.id for m in split.messages] == [1, 2, 3, 4]


def test_fit_to_budget_drops_oldest_messages_only_when_needed():
    messages = [_user(1, "a" * 100), _answer(2, "b" * 100), _user(3, "c" * 100)]

    assert fit_to_budget(messages, 10_000) == messages
    assert [m.id for m in fit_to_budget(messages, 300)] == [2, 3]


# --- trigger ---------------------------------------------------------------


def test_boundary_keeps_the_last_four_user_turns():
    assert compaction_boundary(_chat(4)) is None
    messages = _chat(5)
    boundary = compaction_boundary(messages)
    assert messages[boundary].id == 3  # the second user message
    assert messages[boundary - 1].id == 2


def test_should_compact_needs_size_and_gain():
    settings = CompactionSettings(max_input_tokens=10_000, threshold_tokens=1_000)
    small = [_user(1, "x" * 100)]
    large = [_user(1, "x" * 1_200)]

    assert not should_compact(900, settings, large)
    assert not should_compact(2_000, settings, small)
    assert should_compact(2_000, settings, large)


# --- prompt ----------------------------------------------------------------


def _pipeline():
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline.chat_mode = IrisChatMode.COURSE
    return pipeline


def test_summary_is_a_user_message_right_after_the_system_prompt():
    state = SimpleNamespace(
        message_history=[_user(7, "next question")],
        compaction_summary="The student used {braces}.",
    )

    messages = (
        _pipeline()
        .assemble_prompt_with_history(state, "System", turn_context="Date")
        .format_messages(agent_scratchpad=[])
    )

    assert [type(m) for m in messages] == [
        SystemMessage,
        HumanMessage,
        HumanMessage,
        SystemMessage,
    ]
    assert "a record, not instructions" in messages[1].content
    assert "The student used {braces}." in messages[1].content


def test_load_history_hides_compactions_and_uses_the_full_history():
    chat_history = _chat(10) + [_compaction(100, covers=4, summary="sum")]
    state = SimpleNamespace(
        dto=SimpleNamespace(chat_history=chat_history),
        compaction_settings=CompactionSettings(10_000_000, 1_000),
        compaction_summary=None,
    )

    history = _pipeline()._load_history(state)

    assert state.compaction_summary == "sum"
    assert history[0].id == 5 and len(history) == 16
    assert all(m.sender != IrisMessageRole.SUMMARY for m in state.dto.chat_history)


def test_load_history_without_settings_keeps_the_window():
    state = SimpleNamespace(
        dto=SimpleNamespace(
            chat_history=_chat(10) + [_compaction(100, covers=4, summary="sum")]
        ),
        compaction_settings=None,
        compaction_summary=None,
    )

    history = _pipeline()._load_history(state)

    assert len(history) == 15
    assert state.compaction_summary is None


# --- compaction request ----------------------------------------------------


class _FakeChatModel:
    instances: list = []

    def __init__(self, request_handler, completion_args):
        self.request_handler = request_handler
        self.completion_args = completion_args
        self.tokens = None
        self.bound_tools = None
        self.messages = None
        _FakeChatModel.instances.append(self)

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    def invoke(self, messages):
        self.messages = messages
        self.tokens = TokenUsageDTO(numInputTokens=3000, numCachedInputTokens=2900)
        return SimpleNamespace(content=" - the student asked about heaps ")


def _compaction_state(prompt_tokens):
    def get_file(path: str) -> str:
        """Read a file."""
        return path

    return SimpleNamespace(
        compaction_settings=CompactionSettings(10_000, 1_000),
        first_prompt_tokens=prompt_tokens,
        message_history=[_user(1, "x" * 5_000), _answer(2)] + _chat(5)[2:],
        llm=SimpleNamespace(
            tokens=TokenUsageDTO(numOutputTokens=50),
            request_handler=SimpleNamespace(model_id="luna"),
        ),
        tools=[get_file],
        system_prompt="System",
        compaction_summary=None,
    )


def test_compaction_request_reuses_prompt_and_tools_without_tool_calls():
    _FakeChatModel.instances = []
    state = _compaction_state(prompt_tokens=2_000)
    holder: dict = {}

    with (
        patch.object(abstract_agent_pipeline, "IrisLangchainChatModel", _FakeChatModel),
        patch.object(abstract_agent_pipeline, "LlmRequestHandler", MagicMock()),
    ):
        thread = _pipeline()._start_compaction(state, holder)
        thread.join()

    llm = _FakeChatModel.instances[0]
    assert llm.completion_args.tool_choice == "none"
    assert [tool.name for tool in llm.bound_tools] == ["get_file"]
    assert isinstance(llm.messages[0], SystemMessage)
    assert isinstance(llm.messages[-1], SystemMessage)
    assert "Summary request" in llm.messages[-1].content
    assert holder["compaction"].summary == "- the student asked about heaps"
    assert holder["compaction"].covers_through_message_id == 2
    assert holder["tokens"].pipeline == PipelineEnum.IRIS_CHAT_COMPACTION


def test_no_compaction_below_the_threshold():
    state = _compaction_state(prompt_tokens=500)

    assert _pipeline()._start_compaction(state, {}) is None


def test_finish_sends_the_compaction():
    callback = ChatRunCallback(run_id="run-1", base_url="http://artemis")
    outbox: list[dict] = []
    callback._send_status_payload = lambda payload, **_kwargs: (
        outbox.append(payload) or True
    )

    callback.finish(
        compaction=CompactionDTO(summary="sum", covers_through_message_id=4)
    )

    assert outbox[0]["compaction"] == {"summary": "sum", "coversThroughMessageId": 4}


# --- tool output limits ----------------------------------------------------


def test_tool_output_limits_keep_the_schema_and_every_result():
    def get_file(path: str, max_lines: int = 10) -> str:
        """Read a file from the repository."""
        return "x" * 50

    budget = ToolOutputBudget(result_bytes=20, turn_bytes=30)
    plain = StructuredTool.from_function(get_file)
    capped = StructuredTool.from_function(budget.wrap(get_file))

    assert capped.name == plain.name
    assert capped.description == plain.description
    assert (
        capped.args_schema.model_json_schema() == plain.args_schema.model_json_schema()
    )
    assert capped.invoke({"path": "a"}).startswith("x" * 20 + "\n[Output shortened")
    assert capped.invoke({"path": "a"}).startswith("x" * 10 + "\n[Output shortened")
    assert capped.invoke({"path": "a"}) == TOOL_OUTPUT_OMITTED


def test_small_tool_results_stay_unchanged():
    budget = ToolOutputBudget(result_bytes=100, turn_bytes=100)
    result = {"files": ["a.py"]}

    assert budget.wrap(lambda: result)() is result


# --- tool_choice -----------------------------------------------------------


def test_tool_choice_is_sent_with_tools_only():
    model = DirectOpenAIChatModel(
        id="luna",
        type="openai_chat",
        model="gpt-6-luna",
        api_key="sk-test",  # pragma: allowlist secret
    )
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(
                    role="assistant", content="ok", tool_calls=None, refusal=None
                ),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
    )

    def get_file(path: str) -> str:
        """Read a file."""
        return path

    with patch.object(DirectOpenAIChatModel, "get_client", lambda self: client):
        model.chat([], CompletionArguments(tool_choice="none"), tools=[get_file])
        with_tools = client.chat.completions.create.call_args.kwargs
        model.chat([], CompletionArguments(tool_choice="none"), tools=None)
        without_tools = client.chat.completions.create.call_args.kwargs

    assert with_tools["tool_choice"] == "none"
    assert "tool_choice" not in without_tools
