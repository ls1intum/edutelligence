"""Latency-critical ordering tests for the unified chat pipeline."""

# pylint: skip-file

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Bootstrap the iris package: importing iris.llm directly hits a pre-existing
# circular import between iris.common.pyris_message and iris.domain. Loading
# iris.pipeline.pipeline first establishes the right module init order.
import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.llm.external.openai_chat import (  # noqa: E402
    AzureOpenAIChatModel,
    DirectOpenAIChatModel,
)
from iris.pipeline.chat.chat_pipeline import ChatPipeline  # noqa: E402
from iris.pipeline.chat.iris_chat_mode import IrisChatMode  # noqa: E402
from iris.tools.chat_tool_providers import provide_mcq_generation  # noqa: E402


class _RecordingCallback:
    def __init__(self, call_log: list[str]):
        self.call_log = call_log
        self.calls: list[tuple[str, tuple, dict]] = []
        self.terminal = False

    def activity_snapshot(self, activities, seq):
        self.calls.append(("activity_snapshot", (activities, seq), {}))
        self.call_log.append("activity_snapshot")

    def update(self, **kwargs):
        if self.terminal:
            return False
        self.calls.append(("update", (), kwargs))
        self.call_log.append("update")
        return True

    def send_result(self, *args, **kwargs):
        if self.terminal:
            return False
        self.calls.append(("send_result", args, kwargs))
        self.call_log.append("send_result")
        return True

    def send_suggestions(self, *args, **kwargs):
        if self.terminal:
            return False
        self.calls.append(("send_suggestions", args, kwargs))
        self.call_log.append("send_suggestions")
        return True

    def finish(self, *args, **kwargs):
        if self.terminal:
            return False
        self.terminal = True
        self.calls.append(("finish", args, kwargs))
        self.call_log.append("finish")
        return True

    def fail(self, *args, **kwargs):
        if self.terminal:
            return False
        self.terminal = True
        self.calls.append(("fail", args, kwargs))
        self.call_log.append("fail")
        return True

    def calls_named(self, name: str) -> list[tuple[tuple, dict]]:
        return [
            (args, kwargs)
            for call_name, args, kwargs in self.calls
            if call_name == name
        ]


def _make_dto():
    return SimpleNamespace(
        chat_history=[],
        user=SimpleNamespace(id=1, lang_key="en", memiris_enabled=False),
        course=SimpleNamespace(
            id=7,
            name="Test Course",
            competencies=[],
            exercises=[],
            student_analytics_dashboard_enabled=False,
        ),
        lecture=None,
        programming_exercise=None,
        text_exercise=None,
        settings=None,
        session_title=None,
        metrics=None,
        context=None,
        custom_instructions="",
    )


def _make_pipeline(chat_mode: IrisChatMode, call_log: list[str]) -> ChatPipeline:
    """Create a ChatPipeline without running its heavy __init__."""
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline.chat_mode = chat_mode
    pipeline.event = None

    def generate_title(*_args, **_kwargs):
        call_log.append("title_pipeline")
        return "UPDATE: Fancy Title"

    title_pipeline = MagicMock(side_effect=generate_title)
    title_pipeline.tokens = None
    pipeline.session_title_pipeline = title_pipeline

    citation_pipeline = MagicMock()
    citation_pipeline.tokens = []
    pipeline.citation_pipeline = citation_pipeline

    def generate_suggestions(*_args, **_kwargs):
        call_log.append("suggestion_pipeline")
        return ["suggestion 1"]

    suggestion_pipeline = MagicMock(side_effect=generate_suggestions)
    suggestion_pipeline.tokens = None
    pipeline.suggestion_pipeline = suggestion_pipeline

    pipeline.mcq_pipeline = MagicMock()

    # Stub out everything before the agent loop; these tests only assert the
    # post-agent callback ordering.
    pipeline.prepare_state = lambda state: None
    pipeline.build_system_message = lambda state: "system prompt"
    pipeline.get_tools = lambda state: []
    pipeline.execute_agent = lambda state: "agent answer"
    pipeline.create_tracing_context = lambda dto, variant: None
    return pipeline


def _run_pipeline(pipeline: ChatPipeline, callback: _RecordingCallback) -> None:
    variant = MagicMock()
    variant.id = "default"
    variant.model.return_value = "some-model-id"
    with (
        patch("iris.pipeline.abstract_agent_pipeline.VectorDatabase"),
        patch("iris.pipeline.abstract_agent_pipeline.MemirisWrapper"),
        patch("iris.pipeline.abstract_agent_pipeline.LlmRequestHandler"),
        patch("iris.pipeline.abstract_agent_pipeline.IrisLangchainChatModel"),
    ):
        pipeline(_make_dto(), variant, callback)


def _status_calls(callback: _RecordingCallback) -> list[str]:
    return [
        name
        for name, _args, _kwargs in callback.calls
        if name in {"send_result", "send_suggestions", "finish", "fail"}
    ]


def test_course_mode_sends_result_suggestions_finish_in_order():
    call_log: list[str] = []
    pipeline = _make_pipeline(IrisChatMode.COURSE, call_log)
    callback = _RecordingCallback(call_log)

    _run_pipeline(pipeline, callback)

    assert _status_calls(callback) == ["send_result", "send_suggestions", "finish"]
    assert call_log.index("send_result") < call_log.index("title_pipeline")
    assert call_log.index("send_result") < call_log.index("suggestion_pipeline")

    send_result_args, send_result_kwargs = callback.calls_named("send_result")[0]
    assert send_result_args == ("agent answer",)
    assert send_result_kwargs["tokens"] == []
    assert send_result_kwargs["accessed_memories"] == []
    assert send_result_kwargs["activities"] == []
    assert isinstance(send_result_kwargs["activity_seq"], int)

    send_suggestions_args, send_suggestions_kwargs = callback.calls_named(
        "send_suggestions"
    )[0]
    assert send_suggestions_args == (["suggestion 1"],)
    assert send_suggestions_kwargs["session_title"] == "Fancy Title"
    assert callback.calls_named("finish")[0][1]["session_title"] is None


def test_lecture_mode_sends_result_finish_in_order():
    call_log: list[str] = []
    pipeline = _make_pipeline(IrisChatMode.LECTURE, call_log)
    callback = _RecordingCallback(call_log)

    _run_pipeline(pipeline, callback)

    assert _status_calls(callback) == ["send_result", "finish"]
    assert callback.calls_named("send_result")[0][0] == ("agent answer",)


def test_deferred_title_is_delivered_with_first_send_after_resolution():
    lecture_log: list[str] = []
    lecture_pipeline = _make_pipeline(IrisChatMode.LECTURE, lecture_log)
    lecture_callback = _RecordingCallback(lecture_log)

    _run_pipeline(lecture_pipeline, lecture_callback)

    assert (
        lecture_callback.calls_named("send_result")[0][1].get("session_title") is None
    )
    assert (
        lecture_callback.calls_named("finish")[0][1]["session_title"] == "Fancy Title"
    )

    course_log: list[str] = []
    course_pipeline = _make_pipeline(IrisChatMode.COURSE, course_log)
    course_callback = _RecordingCallback(course_log)

    _run_pipeline(course_pipeline, course_callback)

    assert course_callback.calls_named("send_result")[0][1].get("session_title") is None
    assert (
        course_callback.calls_named("send_suggestions")[0][1]["session_title"]
        == "Fancy Title"
    )
    assert course_callback.calls_named("finish")[0][1]["session_title"] is None


def test_suggestion_failure_fails_with_deferred_title():
    call_log: list[str] = []
    pipeline = _make_pipeline(IrisChatMode.COURSE, call_log)

    def fail_suggestions(*_args, **_kwargs):
        call_log.append("suggestion_pipeline")
        raise RuntimeError("suggestions down")

    pipeline.suggestion_pipeline.side_effect = fail_suggestions
    callback = _RecordingCallback(call_log)

    _run_pipeline(pipeline, callback)

    assert _status_calls(callback) == ["send_result", "fail"]
    fail_args, fail_kwargs = callback.calls_named("fail")[0]
    assert fail_args == ("Generating interaction suggestions failed.",)
    assert fail_kwargs["session_title"] == "Fancy Title"
    assert "activity_seq" in fail_kwargs


def test_title_failure_does_not_break_the_run():
    """A failing title generation after the answer was sent must neither raise
    nor emit an error callback."""
    call_log: list[str] = []
    pipeline = _make_pipeline(IrisChatMode.LECTURE, call_log)
    pipeline.session_title_pipeline.side_effect = RuntimeError("title model down")
    callback = _RecordingCallback(call_log)

    _run_pipeline(pipeline, callback)

    assert _status_calls(callback) == ["send_result", "finish"]
    assert callback.calls_named("finish")[0][1]["session_title"] is None


def test_mcq_provider_defers_lecture_content_fetch():
    """Constructing the MCQ tool must not hit Weaviate; only invoking it may."""
    state = SimpleNamespace(
        dto=SimpleNamespace(
            programming_exercise=None,
            text_exercise=None,
            course=SimpleNamespace(id=7),
            lecture=None,
            chat_history=[],
            user=SimpleNamespace(lang_key="en"),
        ),
        db=MagicMock(),
        callback=MagicMock(),
        mcq_pipeline=MagicMock(return_value='{"type": "mcq"}'),
        allow_lecture_tool=True,
    )

    with patch(
        "iris.tools.chat_tool_providers.retrieve_lecture_content_for_mcq",
        return_value=("LECTURE CONTENT", []),
    ) as fetch:
        tool = provide_mcq_generation(state)
        assert fetch.call_count == 0

        result = tool("generate a question about sorting")

    assert result == "[MCQ_RESULT]"
    fetch.assert_called_once_with(state.db, 7, lecture_id=None, allow_lecture_tool=True)
    assert state.mcq_pipeline.call_args.kwargs["lecture_content"] == "LECTURE CONTENT"


def test_openai_chat_client_is_reused():
    """The completion client must be created once per model entry, not per call."""
    model = DirectOpenAIChatModel(
        id="m",
        type="openai_chat",
        model="gpt-test",
        api_key="sk-test",  # pragma: allowlist secret
    )
    assert model.get_client() is model.get_client()


def test_azure_chat_client_is_reused():
    model = AzureOpenAIChatModel(
        id="m",
        type="azure_chat",
        model="gpt-test",
        api_key="sk-test",  # pragma: allowlist secret
        endpoint="https://example.openai.azure.com",
        azure_deployment="gpt-test",
        api_version="2024-02-01",
    )
    assert model.get_client() is model.get_client()
