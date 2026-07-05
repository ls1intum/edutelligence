"""Tests for visible assistant messages emitted between tool calls."""

from types import SimpleNamespace

from langchain_core.agents import AgentActionMessageLog
from langchain_core.messages import AIMessage

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.pipeline.abstract_agent_pipeline import AbstractAgentPipeline  # noqa: E402
from iris.pipeline.shared.activity_tracker import ActivityTracker  # noqa: E402


class RecordingCallback:
    """Record intermediate messages sent by the agent loop."""

    def __init__(self, call_log=None):
        self.messages = []
        self.call_log = call_log if call_log is not None else []

    def send_intermediate(self, text, activities=None, activity_seq=None):
        self.messages.append((text, activities, activity_seq))
        self.call_log.append(f"intermediate:{text}")
        return True


class FakeAgentExecutor:
    """Agent executor yielding prebuilt iteration steps."""

    def __init__(self, steps, call_log=None):
        self.steps = steps
        self.call_log = call_log

    def iter(self, params, callbacks=None):  # pylint: disable=unused-argument
        yield from self.steps


class StreamingToolTurnExecutor:
    """Agent executor that simulates streaming reset before yielding a tool step."""

    def __init__(self, action, call_log):
        self.action = action
        self.call_log = call_log

    def iter(self, params, callbacks=None):  # pylint: disable=unused-argument
        self.call_log.append("partial:Let me check.")
        self.call_log.append("partial:None")
        yield {"intermediate_steps": [(self.action, "tool result")]}


class MinimalAgentPipeline(AbstractAgentPipeline[object, object]):
    """Concrete pipeline shell exposing the shared agent loop for tests."""

    def __call__(self, *args, **kwargs):  # pylint: disable=unused-argument
        return None

    def is_memiris_memory_creation_enabled(
        self, state
    ):  # pylint: disable=unused-argument
        return False

    def get_tools(self, state):  # pylint: disable=unused-argument
        return []

    def build_system_message(self, state):  # pylint: disable=unused-argument
        return ""

    def get_memiris_tenant(self, dto):  # pylint: disable=unused-argument
        return ""

    def get_memiris_reference(self, dto):  # pylint: disable=unused-argument
        return None


def make_action(content, reasoning_content=None):
    additional_kwargs = {}
    if reasoning_content is not None:
        additional_kwargs["reasoning_content"] = reasoning_content
    message = AIMessage(
        content=content,
        tool_calls=[{"name": "lookup", "args": {"query": "iris"}, "id": "call_1"}],
        additional_kwargs=additional_kwargs,
    )
    return AgentActionMessageLog(
        tool="lookup",
        tool_input={"query": "iris"},
        log="",
        message_log=[message],
    )


def make_state(callback):
    return SimpleNamespace(
        activity_tracker=ActivityTracker(lambda items, seq: None),
        callback=callback,
        llm=None,
        tokens=[],
        tracing_context=None,
    )


def test_agent_loop_emits_visible_tool_turn_content_once():
    callback = RecordingCallback()
    pipeline = MinimalAgentPipeline()
    visible_action = make_action(
        "Let me check first.",
        reasoning_content="hidden chain of thought",
    )
    duplicate_action = make_action("Let me check first.")
    empty_action = make_action("", reasoning_content="do not leak this")
    whitespace_action = make_action("   ")
    executor = FakeAgentExecutor(
        [
            {"intermediate_steps": [(visible_action, "tool result")]},
            {"intermediate_steps": [(duplicate_action, "tool result")]},
            {"intermediate_steps": [(empty_action, "tool result")]},
            {"intermediate_steps": [(whitespace_action, "tool result")]},
        ]
    )

    pipeline._run_agent_iterations(  # pylint: disable=protected-access
        make_state(callback),
        executor,
        {},
    )

    assert callback.messages == [("Let me check first.", None, None)]


def test_agent_loop_sends_intermediate_after_partial_reset():
    call_log = []
    callback = RecordingCallback(call_log)
    pipeline = MinimalAgentPipeline()
    executor = StreamingToolTurnExecutor(make_action("Let me check."), call_log)

    pipeline._run_agent_iterations(  # pylint: disable=protected-access
        make_state(callback),
        executor,
        {},
    )

    assert call_log == [
        "partial:Let me check.",
        "partial:None",
        "intermediate:Let me check.",
    ]
