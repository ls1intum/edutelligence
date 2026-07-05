"""Latency-critical ordering tests for the unified chat pipeline.

The first ``done(final_result=...)`` callback is what the user perceives as
the answer arriving. These tests pin down that deferrable work (session title
generation, suggestion generation, MCQ grounding-content fetch) does not run
before that callback, and that deferred results still reach Artemis via the
subsequent callbacks.
"""

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


def _make_pipeline(chat_mode: IrisChatMode) -> ChatPipeline:
    """Create a ChatPipeline without running its heavy __init__."""
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline.chat_mode = chat_mode
    pipeline.event = None

    title_pipeline = MagicMock(return_value="UPDATE: Fancy Title")
    title_pipeline.tokens = None
    pipeline.session_title_pipeline = title_pipeline

    citation_pipeline = MagicMock()
    citation_pipeline.tokens = []
    pipeline.citation_pipeline = citation_pipeline

    suggestion_pipeline = MagicMock(return_value=["suggestion 1"])
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


def _run_pipeline(pipeline: ChatPipeline, callback: MagicMock) -> None:
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


def test_first_result_callback_is_sent_before_title_generation():
    """The final-result callback must not wait for the session title LLM call."""
    pipeline = _make_pipeline(IrisChatMode.LECTURE)
    callback = MagicMock()

    order_tracker = MagicMock()
    order_tracker.attach_mock(callback, "callback")
    order_tracker.attach_mock(pipeline.session_title_pipeline, "title_pipeline")

    _run_pipeline(pipeline, callback)

    call_names = [name for name, _, _ in order_tracker.mock_calls]
    first_result_index = call_names.index("callback.done")
    title_index = call_names.index("title_pipeline")
    assert first_result_index < title_index

    first_done = callback.done.call_args_list[0]
    assert first_done.kwargs["final_result"] == "agent answer"
    assert "session_title" not in first_done.kwargs


def test_deferred_title_is_delivered_with_trailing_callback():
    """Lecture chat has no suggestions callback, so the trailing callback
    (memory-creation stage) must carry the deferred session title."""
    pipeline = _make_pipeline(IrisChatMode.LECTURE)
    callback = MagicMock()

    _run_pipeline(pipeline, callback)

    assert callback.done.call_count == 2
    trailing_done = callback.done.call_args_list[1]
    assert trailing_done.kwargs["session_title"] == "Fancy Title"


def test_deferred_title_is_delivered_with_suggestions_callback():
    """Course chat delivers the deferred title with the suggestions callback,
    and the trailing callback must not deliver it again."""
    pipeline = _make_pipeline(IrisChatMode.COURSE)
    callback = MagicMock()

    _run_pipeline(pipeline, callback)

    assert callback.done.call_count == 3
    result_done, suggestions_done, trailing_done = callback.done.call_args_list

    assert result_done.kwargs["final_result"] == "agent answer"
    assert "session_title" not in result_done.kwargs

    assert suggestions_done.kwargs["suggestions"] == ["suggestion 1"]
    assert suggestions_done.kwargs["session_title"] == "Fancy Title"

    assert trailing_done.kwargs["session_title"] is None


def test_suggestions_are_generated_after_first_result_callback():
    pipeline = _make_pipeline(IrisChatMode.COURSE)
    callback = MagicMock()

    order_tracker = MagicMock()
    order_tracker.attach_mock(callback, "callback")
    order_tracker.attach_mock(pipeline.suggestion_pipeline, "suggestion_pipeline")

    _run_pipeline(pipeline, callback)

    call_names = [name for name, _, _ in order_tracker.mock_calls]
    assert call_names.index("callback.done") < call_names.index("suggestion_pipeline")


def test_deferred_title_rides_error_callback_when_suggestions_fail():
    """A suggestions failure sends callback.error(), which terminates the job
    on the Artemis side — the deferred title must ride that error callback
    because no later callback can deliver it."""
    pipeline = _make_pipeline(IrisChatMode.COURSE)
    pipeline.suggestion_pipeline.side_effect = RuntimeError("suggestions down")
    callback = MagicMock()

    _run_pipeline(pipeline, callback)

    callback.error.assert_called_once()
    assert callback.error.call_args.kwargs["session_title"] == "Fancy Title"
    # The trailing callback must not try to deliver the title again.
    trailing_done = callback.done.call_args_list[-1]
    assert trailing_done.kwargs["session_title"] is None


def test_title_failure_does_not_break_the_run():
    """A failing title generation after the answer was sent must neither raise
    nor emit an error callback."""
    pipeline = _make_pipeline(IrisChatMode.LECTURE)
    pipeline.session_title_pipeline.side_effect = RuntimeError("title model down")
    callback = MagicMock()

    _run_pipeline(pipeline, callback)

    callback.error.assert_not_called()
    assert callback.done.call_count == 2
    assert callback.done.call_args_list[1].kwargs["session_title"] is None


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
