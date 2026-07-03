import iris.pipeline.pipeline  # noqa: F401

# isort: skip_file
# pylint: skip-file

import copy
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from iris.config import Settings  # noqa: E402
from iris.pipeline.chat import chat_pipeline as chat_pipeline_module  # noqa: E402
from iris.pipeline.chat.chat_pipeline import ChatPipeline  # noqa: E402
from iris.pipeline.chat.iris_chat_mode import IrisChatMode  # noqa: E402


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
        programming_exercise=SimpleNamespace(
            title="Exercise",
            problem_statement="Implement the exercise.",
            programming_language="Python",
        ),
        text_exercise=None,
        settings=None,
        session_title=None,
        metrics=None,
        context=None,
        custom_instructions="",
        text_exercise_submission="",
    )


def _make_pipeline(chat_mode: IrisChatMode) -> ChatPipeline:
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

    pipeline.prepare_state = lambda state: None
    pipeline.build_system_message = lambda state: "system prompt"
    pipeline.get_tools = lambda state: []
    pipeline.pre_agent_hook = lambda state: None

    def execute_agent(state):
        pipeline._captured_state = state
        return "agent answer"

    pipeline.execute_agent = execute_agent
    pipeline.create_tracing_context = lambda dto, variant: None
    pipeline._track_tokens = MagicMock()
    return pipeline


def _make_refinement_pipeline() -> ChatPipeline:
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline.chat_mode = IrisChatMode.EXERCISE
    pipeline.guide_prompt_template = MagicMock()
    pipeline.guide_prompt_template.render.return_value = "guide prompt"
    pipeline._track_tokens = MagicMock()
    return pipeline


def _make_refinement_state(variant):
    return SimpleNamespace(
        dto=_make_dto(),
        variant=variant,
        local=False,
        callback=MagicMock(),
    )


def _make_variant(chat_model_id: str = "chat-model-id"):
    variant = MagicMock()
    variant.id = "default"
    variant.model.return_value = chat_model_id
    return variant


def _run_pipeline(pipeline: ChatPipeline, callback: MagicMock) -> None:
    variant = MagicMock()
    variant.id = "default"
    variant.model.return_value = "some-model-id"
    with (
        patch("iris.pipeline.abstract_agent_pipeline.VectorDatabase"),
        patch("iris.pipeline.abstract_agent_pipeline.MemirisWrapper"),
        patch("iris.pipeline.abstract_agent_pipeline.LlmRequestHandler"),
        patch("iris.pipeline.abstract_agent_pipeline.IrisLangchainChatModel"),
        patch("iris.pipeline.chat.chat_pipeline.mcq_post_agent_hook"),
    ):
        pipeline(_make_dto(), variant, callback)


@pytest.fixture
def refinement_settings(monkeypatch):
    def apply(mode: str, sample: float = 1.0) -> None:
        monkeypatch.setattr(
            chat_pipeline_module.settings, "exercise_guide_refinement", mode
        )
        monkeypatch.setattr(
            chat_pipeline_module.settings,
            "exercise_guide_refinement_shadow_sample",
            sample,
        )

    return apply


def test_default_refinement_mode_is_blocking():
    assert Settings.model_fields["exercise_guide_refinement"].default == "blocking"


def test_guide_role_configured_uses_guide_model(monkeypatch):
    pipeline = _make_refinement_pipeline()
    variant = _make_variant()
    state = _make_refinement_state(variant)
    captured_model_ids = []

    llm_configuration = copy.deepcopy(chat_pipeline_module.settings.llm_configuration)
    llm_configuration["chat_pipeline"]["default"]["guide"] = {
        "local": "guide-local-model-id",
        "cloud": "guide-cloud-model-id",
    }
    monkeypatch.setattr(
        chat_pipeline_module.settings, "llm_configuration", llm_configuration
    )

    class FakeGuideChain:
        def __or__(self, _other):
            return self

        def invoke(self, _arguments):
            return "Guide rewrite"

    def fake_request_handler(*args, **kwargs):
        captured_model_ids.append(kwargs.get("model_id", args[0] if args else None))
        return MagicMock()

    def fake_chat_model(request_handler, completion_args):
        assert request_handler is not None
        assert completion_args.temperature == 0.5
        assert completion_args.max_tokens == 2000
        return SimpleNamespace(tokens=["guide-token"])

    with (
        patch(
            "iris.pipeline.chat.chat_pipeline.ChatPromptTemplate.from_messages",
            return_value=FakeGuideChain(),
        ),
        patch(
            "iris.pipeline.chat.chat_pipeline.LlmRequestHandler",
            side_effect=fake_request_handler,
        ),
        patch(
            "iris.pipeline.chat.chat_pipeline.IrisLangchainChatModel",
            side_effect=fake_chat_model,
        ),
    ):
        guide_response, refined_response = pipeline._run_guide_refinement(
            state, "Original answer"
        )

    assert guide_response == "Guide rewrite"
    assert refined_response == "Guide rewrite"
    assert captured_model_ids == ["guide-cloud-model-id"]
    variant.model.assert_not_called()
    pipeline._track_tokens.assert_called_once_with(state, ["guide-token"])


def test_guide_role_missing_falls_back_to_chat_model_and_logs_once(monkeypatch, caplog):
    pipeline = _make_refinement_pipeline()
    variant = _make_variant()
    state = _make_refinement_state(variant)
    captured_model_ids = []

    llm_configuration = copy.deepcopy(chat_pipeline_module.settings.llm_configuration)
    llm_configuration["chat_pipeline"]["default"].pop("guide", None)
    monkeypatch.setattr(
        chat_pipeline_module.settings, "llm_configuration", llm_configuration
    )

    class FakeGuideChain:
        def __or__(self, _other):
            return self

        def invoke(self, _arguments):
            return "!ok!"

    def fake_request_handler(*args, **kwargs):
        captured_model_ids.append(kwargs.get("model_id", args[0] if args else None))
        return MagicMock()

    with (
        patch(
            "iris.pipeline.chat.chat_pipeline.ChatPromptTemplate.from_messages",
            return_value=FakeGuideChain(),
        ),
        patch(
            "iris.pipeline.chat.chat_pipeline.LlmRequestHandler",
            side_effect=fake_request_handler,
        ),
        patch(
            "iris.pipeline.chat.chat_pipeline.IrisLangchainChatModel",
            return_value=SimpleNamespace(tokens=["guide-token"]),
        ),
        caplog.at_level(logging.INFO),
    ):
        first_response, first_refined = pipeline._run_guide_refinement(
            state, "Original answer"
        )
        second_response, second_refined = pipeline._run_guide_refinement(
            state, "Original answer"
        )

    assert first_response == "!ok!"
    assert first_refined == "Original answer"
    assert second_response == "!ok!"
    assert second_refined == "Original answer"
    assert captured_model_ids == ["chat-model-id", "chat-model-id"]
    variant.model.assert_called_once_with("chat", False)
    messages = [record.getMessage() for record in caplog.records]
    assert messages.count("guide role not configured — falling back to chat model") == 1


@pytest.mark.parametrize(
    ("guide_response", "expected_final_result"),
    [
        ("Please use a smaller hint.", "Please use a smaller hint."),
        ("!ok!", "agent answer"),
    ],
)
def test_blocking_invokes_guide_before_done_and_uses_guide_result(
    refinement_settings, guide_response, expected_final_result
):
    refinement_settings("blocking")
    pipeline = _make_pipeline(IrisChatMode.EXERCISE)
    pipeline._run_guide_refinement = MagicMock(
        return_value=(guide_response, expected_final_result)
    )
    callback = MagicMock()

    order_tracker = MagicMock()
    order_tracker.attach_mock(callback, "callback")
    order_tracker.attach_mock(pipeline._run_guide_refinement, "guide")

    _run_pipeline(pipeline, callback)

    call_names = [name for name, _, _ in order_tracker.mock_calls]
    assert call_names.index("guide") < call_names.index("callback.done")
    assert (
        callback.done.call_args_list[0].kwargs["final_result"] == expected_final_result
    )
    assert pipeline._captured_state.result == expected_final_result


def test_blocking_failure_delivers_original_without_error_callback(
    refinement_settings,
):
    refinement_settings("blocking")
    pipeline = _make_pipeline(IrisChatMode.EXERCISE)
    pipeline._run_guide_refinement = MagicMock(side_effect=RuntimeError("guide down"))
    callback = MagicMock()

    _run_pipeline(pipeline, callback)

    callback.error.assert_not_called()
    assert callback.done.call_args_list[0].kwargs["final_result"] == "agent answer"
    assert pipeline._captured_state.result == "agent answer"


@pytest.mark.parametrize(
    ("guide_response", "would_have_rewritten"),
    [
        ("Please use a smaller hint.", True),
        ("!ok!", False),
    ],
)
def test_shadow_invokes_guide_after_user_callbacks_and_keeps_original_result(
    refinement_settings, caplog, guide_response, would_have_rewritten
):
    refinement_settings("shadow")
    caplog.set_level(logging.INFO)
    pipeline = _make_pipeline(IrisChatMode.EXERCISE)
    rewrite = "Please use a smaller hint." if would_have_rewritten else "agent answer"
    pipeline._run_guide_refinement = MagicMock(return_value=(guide_response, rewrite))
    callback = MagicMock()

    order_tracker = MagicMock()
    order_tracker.attach_mock(callback, "callback")
    order_tracker.attach_mock(pipeline._run_guide_refinement, "guide")

    _run_pipeline(pipeline, callback)

    call_names = [name for name, _, _ in order_tracker.mock_calls]
    guide_index = call_names.index("guide")
    done_indices = [
        index
        for index, call_name in enumerate(call_names)
        if call_name == "callback.done"
    ]
    assert done_indices[0] < guide_index
    assert done_indices[1] < guide_index
    assert callback.done.call_args_list[0].kwargs["final_result"] == "agent answer"
    assert pipeline._captured_state.result == "agent answer"
    assert (
        "Guide refinement shadow | " f"would_have_rewritten={would_have_rewritten}"
    ) in caplog.text


def test_shadow_sampling_zero_never_invokes_guide(refinement_settings):
    refinement_settings("shadow", sample=0.0)
    pipeline = _make_pipeline(IrisChatMode.EXERCISE)
    pipeline._run_guide_refinement = MagicMock(
        return_value=("Please use a smaller hint.", "Please use a smaller hint.")
    )
    callback = MagicMock()

    with patch("iris.pipeline.chat.chat_pipeline.random.random", return_value=0.0):
        _run_pipeline(pipeline, callback)

    pipeline._run_guide_refinement.assert_not_called()
    assert callback.done.call_args_list[0].kwargs["final_result"] == "agent answer"


def test_off_never_invokes_guide(refinement_settings):
    refinement_settings("off")
    pipeline = _make_pipeline(IrisChatMode.EXERCISE)
    pipeline._run_guide_refinement = MagicMock(
        return_value=("Please use a smaller hint.", "Please use a smaller hint.")
    )
    callback = MagicMock()

    _run_pipeline(pipeline, callback)

    pipeline._run_guide_refinement.assert_not_called()
    assert callback.done.call_args_list[0].kwargs["final_result"] == "agent answer"


@pytest.mark.parametrize(
    "chat_mode",
    [IrisChatMode.COURSE, IrisChatMode.LECTURE, IrisChatMode.TEXT_EXERCISE],
)
@pytest.mark.parametrize("mode", ["blocking", "shadow", "off"])
def test_non_exercise_modes_never_invoke_guide(refinement_settings, chat_mode, mode):
    refinement_settings(mode)
    pipeline = _make_pipeline(chat_mode)
    pipeline._run_guide_refinement = MagicMock(
        return_value=("Please use a smaller hint.", "Please use a smaller hint.")
    )
    callback = MagicMock()

    _run_pipeline(pipeline, callback)

    pipeline._run_guide_refinement.assert_not_called()
