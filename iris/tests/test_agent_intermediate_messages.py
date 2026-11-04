"""Tests for the native agent loop: narration, tool activity, errors and limits."""

# pylint: disable=protected-access

from types import SimpleNamespace

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.pyris_message import (  # noqa: E402
    IrisMessageRole,
    PyrisAIMessage,
    PyrisMessage,
    PyrisToolMessage,
)
from iris.common.token_usage_dto import TokenUsageDTO  # noqa: E402
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.domain.status.activity_dto import ActivityKind, ActivityState
from iris.llm.agent import AgentLoop, AgentTool  # noqa: E402
from iris.pipeline.abstract_agent_pipeline import (  # noqa: E402
    AbstractAgentPipeline,
    TrackerToolActivity,
)
from iris.pipeline.shared.activity_tracker import ActivityTracker  # noqa: E402
from iris.tools.activity_metadata import curate_detail  # noqa: E402


class RecordingCallback:
    """Record intermediate messages sent by the agent loop."""

    def __init__(self, call_log=None):
        self.messages = []
        self.call_log = call_log if call_log is not None else []

    def send_intermediate(self, text, activities=None, activity_seq=None):
        self.messages.append((text, activities, activity_seq))
        self.call_log.append(f"intermediate:{text}")
        return True


class ScriptedModel:
    """Returns prebuilt responses and records what it was sent."""

    def __init__(self, responses, call_log=None, stream_events=None):
        self.responses = list(responses)
        self.calls = []
        self.call_log = call_log
        self.stream_events = list(stream_events or [])
        self.tokens = None
        self.request_handler = SimpleNamespace(model_id="test-model")

    def chat(self, messages, tools=None, tool_choice=None):
        self.calls.append((list(messages), tools, tool_choice))
        if self.stream_events and self.call_log is not None:
            self.call_log.extend(self.stream_events.pop(0))
        self.tokens = TokenUsageDTO(numInputTokens=len(self.calls))
        return self.responses.pop(0)


class MinimalAgentPipeline(AbstractAgentPipeline[object, object]):
    """Concrete pipeline shell exposing the shared agent loop for tests."""

    def __call__(self, *args, **kwargs):  # pylint: disable=unused-argument
        return None

    def get_tools(self, state):  # pylint: disable=unused-argument
        return []

    def build_system_message(self, state):  # pylint: disable=unused-argument
        return ""


def tool_turn(text, name="lookup", arguments='{"query": "iris"}', call_id="call_1"):
    return PyrisAIMessage(
        contents=[TextMessageContentDTO(textContent=text)],
        toolCalls=[
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
        ],
    )


def answer(text):
    return PyrisMessage(
        sender=IrisMessageRole.ASSISTANT,
        contents=[TextMessageContentDTO(textContent=text)],
    )


def lookup(query: str) -> str:
    """Look something up."""
    return f"result for {query}"


def make_state(callback, model, tools=None, tracker=None):
    return SimpleNamespace(
        activity_tracker=tracker or ActivityTracker(lambda items, seq: None),
        callback=callback,
        llm=model,
        tokens=[],
        tracing_context=None,
        tools=tools if tools is not None else [lookup],
        prompt_messages=[answer("system")],
    )


def test_agent_loop_emits_visible_tool_turn_content_once():
    callback = RecordingCallback()
    model = ScriptedModel(
        [
            tool_turn("Let me check first."),
            tool_turn("Let me check first."),
            tool_turn(""),
            tool_turn("   "),
            answer("Done."),
        ]
    )

    result = MinimalAgentPipeline()._run_agent_loop(make_state(callback, model))

    assert result == "Done."
    assert callback.messages == [("Let me check first.", None, None)]


def test_agent_loop_sends_intermediate_after_partial_reset():
    call_log = []
    callback = RecordingCallback(call_log)
    model = ScriptedModel(
        [tool_turn("Let me check."), answer("Done.")],
        call_log=call_log,
        stream_events=[["partial:Let me check.", "partial:None"], []],
    )

    MinimalAgentPipeline()._run_agent_loop(make_state(callback, model))

    assert call_log == [
        "partial:Let me check.",
        "partial:None",
        "intermediate:Let me check.",
    ]


def test_narration_reaches_the_student_before_the_tool_starts():
    order = []
    tracker = ActivityTracker(lambda items, seq: None)
    original_start = tracker.start

    def recording_start(kind, name, detail=None):
        order.append(("tool_start", name))
        return original_start(kind, name, detail=detail)

    tracker.start = recording_start
    callback = SimpleNamespace(
        send_intermediate=lambda text: order.append(("narrate", text))
    )
    model = ScriptedModel([tool_turn("Let me check the lecture."), answer("Done.")])

    MinimalAgentPipeline()._run_agent_loop(make_state(callback, model, tracker=tracker))

    assert order == [("narrate", "Let me check the lecture."), ("tool_start", "lookup")]


def test_tool_results_go_back_to_the_model_in_order():
    model = ScriptedModel([tool_turn("", arguments='{"query": "heaps"}'), answer("ok")])

    MinimalAgentPipeline()._run_agent_loop(make_state(RecordingCallback(), model))

    second_request = model.calls[1][0]
    assert isinstance(second_request[-2], PyrisAIMessage)
    tool_message = second_request[-1]
    assert isinstance(tool_message, PyrisToolMessage)
    assert tool_message.contents[0].tool_content == "result for heaps"
    assert tool_message.contents[0].tool_call_id == "call_1"
    assert tool_message.contents[0].name == "lookup"


def test_a_failing_tool_becomes_an_observation_and_a_failed_activity():
    snapshots = []
    tracker = ActivityTracker(lambda items, seq: snapshots.append(items))

    def broken(query: str) -> str:
        """Always fails."""
        raise RuntimeError(f"backend down for {query}")

    model = ScriptedModel([tool_turn("", name="broken"), answer("Sorry.")])
    state = make_state(RecordingCallback(), model, tools=[broken], tracker=tracker)

    assert MinimalAgentPipeline()._run_agent_loop(state) == "Sorry."

    observation = model.calls[1][0][-1].contents[0].tool_content
    assert observation == "backend down for iris"
    assert snapshots[-1][0].state == ActivityState.FAILED


def test_unknown_tool_and_bad_arguments_are_reported_to_the_model():
    model = ScriptedModel(
        [
            tool_turn("", name="does_not_exist"),
            tool_turn("", arguments='{"wrong": 1}', call_id="call_2"),
            answer("ok"),
        ]
    )

    MinimalAgentPipeline()._run_agent_loop(make_state(RecordingCallback(), model))

    observations = [call[0][-1].contents[0].tool_content for call in model.calls[1:]]
    assert "no tool named 'does_not_exist'" in observations[0]
    assert "Unknown argument(s) for lookup: wrong" in observations[1]


def test_step_limit_forces_a_final_answer_without_tool_calls():
    model = ScriptedModel(
        [tool_turn("", call_id=f"call_{i}") for i in range(3)] + [answer("Final.")]
    )
    loop = AgentLoop(model=model, tools=[AgentTool.from_function(lookup)], max_steps=3)

    result = loop.run([answer("system")])

    assert result.output == "Final."
    assert result.hit_step_limit
    assert model.calls[-1][2] == "none"


def test_step_limit_without_tool_choice_support_sends_no_tools():
    model = ScriptedModel([tool_turn("", call_id="call_1"), answer("Final.")])
    loop = AgentLoop(
        model=model,
        tools=[AgentTool.from_function(lookup)],
        max_steps=1,
        supports_tool_choice=False,
    )

    assert loop.run([answer("system")]).output == "Final."
    messages, tools, tool_choice = model.calls[-1]
    assert tools is None and tool_choice is None
    assert messages[-1].sender == IrisMessageRole.SYSTEM


def test_activity_uses_the_curated_detail_and_raw_result():
    snapshots = []
    tracker = ActivityTracker(lambda items, seq: snapshots.append(items))
    activity = TrackerToolActivity(tracker)

    handle = activity.tool_started(
        "lecture_content_retrieval", {"query": "sorting algorithms"}
    )
    activity.tool_finished(handle, "lecture_content_retrieval", ["one", "two"])

    item = snapshots[-1][0]
    assert item.kind == ActivityKind.TOOL
    assert item.detail == "sorting algorithms"
    assert item.result == "2 sections"
    assert item.state == ActivityState.FINISHED


def test_activity_survives_a_curation_error(monkeypatch, caplog):
    snapshots = []
    activity = TrackerToolActivity(
        ActivityTracker(lambda items, seq: snapshots.append(items))
    )

    def explode(unused_tool_name, unused_inputs):
        raise RuntimeError("curation failed")

    monkeypatch.setattr("iris.pipeline.abstract_agent_pipeline.curate_detail", explode)

    handle = activity.tool_started("lecture_content_retrieval", {"query": "sorting"})

    assert handle is None
    assert not snapshots
    assert "Activity tracking failed during tool start" in caplog.text


def test_curated_detail_is_cut_to_120_characters():
    assert curate_detail("faq_content_retrieval", {"query": "x" * 150}) == "x" * 120


def test_tool_schema_is_strict_compatible():
    def search(query: str, limit: int = 5, unit: int | None = None) -> str:
        """Search."""
        return f"{query} {limit} {unit}"

    tool = AgentTool.from_function(search)

    assert tool.parameters["required"] == ["query", "limit", "unit"]
    assert tool.parameters["additionalProperties"] is False
    assert {"type": "null"} in tool.parameters["properties"]["limit"]["anyOf"]
    assert tool.openai_schema(strict=True)["function"]["strict"] is True
    # Null falls back to the default; the model may leave optional values out.
    assert tool.bind_arguments({"query": "q", "limit": None, "unit": None}) == {
        "query": "q"
    }
