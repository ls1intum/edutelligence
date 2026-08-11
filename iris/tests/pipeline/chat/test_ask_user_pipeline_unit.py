from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from iris.domain.data.verdict_dto import VerdictDTO
from iris.pipeline.chat.ask_user_pipeline import AskUserPipeline
from iris.pipeline.prompts.templates.ask_user.verdict_dependent_placeholder import VERDICT_DEPENDENT


def _make_pipeline() -> AskUserPipeline:
    # AskUserPipeline() safely constructs a real AssessUserAnswerPipeline and
    # loads the real Jinja templates from disk; no network I/O happens here.
    return AskUserPipeline()


def _make_dto(
    problem_statement="Implement bubble sort.",
    programming_language="JAVA",
    exercise_title="Bubble Sort",
    lang_key="en",
    submission=None,
):
    return SimpleNamespace(
        programming_exercise=SimpleNamespace(
            title=exercise_title,
            name=None,
            problem_statement=problem_statement,
            programming_language=programming_language,
        ),
        programming_exercise_submission=submission,
        user=SimpleNamespace(id=1, lang_key=lang_key),
        chat_history=[],
    )


def _make_state(dto=None, callback=None, message_history=None, **extra):
    state = SimpleNamespace(
        dto=dto if dto is not None else _make_dto(),
        callback=callback if callback is not None else MagicMock(),
        message_history=message_history if message_history is not None else [],
        **extra,
    )
    return state


# --------------------------------------------------------------------------
# get_variants
# --------------------------------------------------------------------------


def test_get_variants_returns_default_and_advanced():
    variants = AskUserPipeline.get_variants()

    ids = [v.id for v in variants]
    assert ids == ["default", "advanced"]
    assert variants[0].agent_model == "oai-gpt-5-mini"
    assert variants[1].agent_model == "oai-gpt-52"
    assert variants[1].guide_model == "oai-gpt-5-mini"


# --------------------------------------------------------------------------
# memiris hooks
# --------------------------------------------------------------------------


def test_memory_creation_is_disabled():
    pipeline = _make_pipeline()

    assert pipeline.is_memiris_memory_creation_enabled(state=MagicMock()) is False


def test_get_memiris_reference_is_unknown():
    pipeline = _make_pipeline()

    assert pipeline.get_memiris_reference(dto=MagicMock()) == "unknown"


def test_get_memiris_tenant_requires_user():
    pipeline = _make_pipeline()
    dto = SimpleNamespace(user=None)

    with pytest.raises(ValueError):
        pipeline.get_memiris_tenant(dto)


def test_get_memiris_tenant_delegates_to_helper():
    pipeline = _make_pipeline()
    dto = SimpleNamespace(user=SimpleNamespace(id=42))

    with patch(
        "iris.pipeline.chat.ask_user_pipeline.get_tenant_for_user",
        return_value="tenant-42",
    ) as get_tenant:
        assert pipeline.get_memiris_tenant(dto) == "tenant-42"
    get_tenant.assert_called_once_with(42)


# --------------------------------------------------------------------------
# _get_exercise_title
# --------------------------------------------------------------------------


def test_get_exercise_title_empty_without_exercise():
    dto = SimpleNamespace(programming_exercise=None)

    assert AskUserPipeline._get_exercise_title(dto) == ""


def test_get_exercise_title_prefers_title_over_name():
    dto = SimpleNamespace(
        programming_exercise=SimpleNamespace(title="Bubble Sort", name="ignored")
    )

    assert AskUserPipeline._get_exercise_title(dto) == "Bubble Sort"


def test_get_exercise_title_falls_back_to_name_when_title_missing():
    dto = SimpleNamespace(
        programming_exercise=SimpleNamespace(title=None, name="Fallback")
    )

    assert AskUserPipeline._get_exercise_title(dto) == "Fallback"


# --------------------------------------------------------------------------
# build_system_message
# --------------------------------------------------------------------------


def test_build_system_message_renders_exercise_context():
    pipeline = _make_pipeline()
    pipeline.event = None
    pipeline.chat_history_needed = False
    state = _make_state(dto=_make_dto())

    message = pipeline.build_system_message(state)

    assert "Bubble Sort" in message
    assert "java" in message  # programming_language is lower-cased
    assert "Implement bubble sort." in message
    assert (
        VERDICT_DEPENDENT in message
    )  # self.event is None -> verdict-dependent branch


def test_build_system_message_lowercases_programming_language():
    pipeline = _make_pipeline()
    pipeline.event = None
    pipeline.chat_history_needed = False
    state = _make_state(dto=_make_dto(programming_language="JAVA"))

    message = pipeline.build_system_message(state)

    assert "JAVA" not in message
    assert "java" in message


def test_build_system_message_uses_first_question_branch_for_event():
    pipeline = _make_pipeline()
    pipeline.event = "FIRST_QUESTION"
    pipeline.chat_history_needed = False
    state = _make_state(dto=_make_dto())

    message = pipeline.build_system_message(state)

    assert VERDICT_DEPENDENT not in message
    assert "Now generate the first question." in message


def test_build_system_message_handles_missing_programming_exercise():
    pipeline = _make_pipeline()
    pipeline.event = None
    pipeline.chat_history_needed = False
    dto = _make_dto()
    dto.programming_exercise = None
    state = _make_state(dto=dto)

    # Must not raise despite problem_statement/programming_language being unset.
    message = pipeline.build_system_message(state)
    assert isinstance(message, str)


# --------------------------------------------------------------------------
# on_agent_step
# --------------------------------------------------------------------------


def test_on_agent_step_reports_progress_when_there_are_intermediate_steps():
    pipeline = _make_pipeline()
    callback = MagicMock()
    state = _make_state(callback=callback)

    pipeline.on_agent_step(state, {"intermediate_steps": [object()]})

    callback.update.assert_called_once_with()


def test_on_agent_step_is_silent_without_intermediate_steps():
    pipeline = _make_pipeline()
    callback = MagicMock()
    state = _make_state(callback=callback)

    pipeline.on_agent_step(state, {"intermediate_steps": []})

    callback.update.assert_not_called()


# --------------------------------------------------------------------------
# pre_agent_hook
# --------------------------------------------------------------------------


def test_pre_agent_hook_assesses_answer_when_no_event():
    pipeline = _make_pipeline()
    pipeline.event = None
    pipeline._assess_answer = MagicMock()
    state = _make_state()

    pipeline.pre_agent_hook(state)

    pipeline._assess_answer.assert_called_once_with(state)


def test_pre_agent_hook_skips_assessment_for_special_events():
    pipeline = _make_pipeline()
    pipeline.event = "TAB_DEFOCUS"
    pipeline._assess_answer = MagicMock()
    state = _make_state()

    pipeline.pre_agent_hook(state)

    pipeline._assess_answer.assert_not_called()


def test_pre_agent_hook_reports_error_on_exception():
    pipeline = _make_pipeline()
    pipeline.event = None
    pipeline._assess_answer = MagicMock(side_effect=RuntimeError("boom"))
    callback = MagicMock()
    state = _make_state(callback=callback)

    pipeline.pre_agent_hook(state)

    callback.fail.assert_called_once()


# --------------------------------------------------------------------------
# post_agent_hook
# --------------------------------------------------------------------------


def _post_hook_state(event, verdict, result="agent answer"):
    pipeline = _make_pipeline()
    pipeline.event = event
    pipeline.verdict = verdict
    pipeline._refine_response = MagicMock(return_value="refined answer")
    callback = MagicMock()
    callback.status = SimpleNamespace(event=None)
    state = _make_state(callback=callback, result=result, tokens=[])
    return pipeline, state, callback


def test_post_agent_hook_refines_response_on_first_question():
    pipeline, state, callback = _post_hook_state(event="FIRST_QUESTION", verdict=None)

    pipeline.post_agent_hook(state)

    pipeline._refine_response.assert_called_once_with(state)
    assert callback.update.call_args.kwargs["result"] == "refined answer"


def test_post_agent_hook_refines_response_on_next_question_verdict():
    verdict = VerdictDTO(verdict="NEXT_QUESTION", reasoning="Too vague.")
    pipeline, state, callback = _post_hook_state(event=None, verdict=verdict)

    pipeline.post_agent_hook(state)

    pipeline._refine_response.assert_called_once_with(state)
    assert callback.update.call_args.kwargs["result"] == "refined answer"
    assert callback.status.event == "NEXT_QUESTION"
    # NEXT_QUESTION verdicts are not accepted by the Artemis API and must be
    # cleared before being sent, while reasoning is preserved.
    sent_verdict = callback.update.call_args.kwargs["verdict"]
    assert sent_verdict.verdict is None
    assert sent_verdict.reasoning == "Too vague."


def test_post_agent_hook_uses_raw_result_without_refinement_otherwise():
    verdict = VerdictDTO(verdict="UNSUSPICIOUS", reasoning="Good understanding.")
    pipeline, state, callback = _post_hook_state(event=None, verdict=verdict)

    pipeline.post_agent_hook(state)

    pipeline._refine_response.assert_not_called()
    assert callback.update.call_args.kwargs["result"] == "agent answer"
    assert callback.status.event == "QUIZ_FINISHED"


def test_post_agent_hook_marks_suspicious_on_tab_defocus():
    pipeline, state, callback = _post_hook_state(event="TAB_DEFOCUS", verdict=None)

    pipeline.post_agent_hook(state)

    sent_verdict = callback.update.call_args.kwargs["verdict"]
    assert sent_verdict.verdict == "SUSPICIOUS"
    assert sent_verdict.reasoning == "Tab defocus!"
    assert callback.status.event == "QUIZ_FINISHED"


def test_post_agent_hook_marks_suspicious_on_timer_ran_out():
    pipeline, state, callback = _post_hook_state(event="TIMER_RAN_OUT", verdict=None)

    pipeline.post_agent_hook(state)

    sent_verdict = callback.update.call_args.kwargs["verdict"]
    assert sent_verdict.verdict == "SUSPICIOUS"
    assert sent_verdict.reasoning == "Time limit exceeded!"


def test_post_agent_hook_forwards_event_when_no_verdict():
    pipeline, state, callback = _post_hook_state(
        event="BUILD_WITH_POINTS", verdict=None
    )

    pipeline.post_agent_hook(state)

    assert callback.status.event == "BUILD_WITH_POINTS"
    assert callback.update.call_args.kwargs["verdict"] is None


def test_post_agent_hook_resets_verdict_after_success():
    pipeline, state, _callback = _post_hook_state(
        event=None, verdict=VerdictDTO(verdict="UNSUSPICIOUS", reasoning="ok")
    )

    pipeline.post_agent_hook(state)

    assert pipeline.verdict is None


def test_post_agent_hook_reports_error_and_resets_verdict_on_exception():
    pipeline, state, callback = _post_hook_state(event="FIRST_QUESTION", verdict=None)
    pipeline._refine_response = MagicMock(side_effect=RuntimeError("boom"))

    pipeline.post_agent_hook(state)

    callback.fail.assert_called_once()
    callback.update.assert_not_called()
    assert pipeline.verdict is None


# --------------------------------------------------------------------------
# _refine_response
# --------------------------------------------------------------------------


class _FakeGuideChain:
    def __init__(self, response):
        self.response = response

    def __or__(self, _other):
        return self

    def invoke(self, _arguments):
        return self.response


def _refine_pipeline(guide_response):
    pipeline = _make_pipeline()
    pipeline.guide_prompt_template = MagicMock()
    pipeline.guide_prompt_template.render.return_value = "guide prompt"
    pipeline._track_tokens = MagicMock()
    variant = MagicMock()
    variant.model.return_value = "guide-model-id"
    state = _make_state(
        dto=_make_dto(), result="original question", variant=variant, local=False
    )

    with (
        patch(
            "iris.pipeline.chat.ask_user_pipeline.ChatPromptTemplate.from_messages",
            return_value=_FakeGuideChain(guide_response),
        ),
        patch("iris.pipeline.chat.ask_user_pipeline.LlmRequestHandler"),
        patch(
            "iris.pipeline.chat.ask_user_pipeline.IrisLangchainChatModel",
            return_value=SimpleNamespace(tokens=["guide-token"]),
        ),
    ):
        result = pipeline._refine_response(state)

    return pipeline, state, result


def test_refine_response_keeps_original_when_guide_says_ok():
    pipeline, state, result = _refine_pipeline("!ok!")

    assert result == "original question"
    pipeline._track_tokens.assert_called_once_with(state, ["guide-token"])


def test_refine_response_uses_rewritten_question_otherwise():
    _pipeline, _state, result = _refine_pipeline("Why does this loop terminate?")

    assert result == "Why does this loop terminate?"


def test_refine_response_falls_back_to_original_on_exception():
    pipeline = _make_pipeline()
    pipeline.guide_prompt_template = MagicMock()
    pipeline.guide_prompt_template.render.side_effect = RuntimeError("template broken")
    callback = MagicMock()
    state = _make_state(dto=_make_dto(), result="original question", callback=callback)

    result = pipeline._refine_response(state)

    assert result == "original question"
    callback.fail.assert_called_once()


# --------------------------------------------------------------------------
# _assess_answer
# --------------------------------------------------------------------------


class _RecordingSystemPrompt:
    def __init__(self, template):
        self.template = template


class _RecordingMessage:
    def __init__(self, template):
        self.prompt = _RecordingSystemPrompt(template)


def _assess_answer_state(assessment_result_text):
    from langchain_core.prompts import SystemMessagePromptTemplate

    pipeline = _make_pipeline()
    pipeline.assess_user_answer_pipeline = MagicMock(
        return_value=assessment_result_text, tokens=None
    )
    pipeline.verdict_dependent_template = MagicMock()
    pipeline.verdict_dependent_template.render.return_value = "Ask another {question}!"

    system_message = SystemMessagePromptTemplate.from_template(
        "prefix " + VERDICT_DEPENDENT + " suffix", template_format="jinja2"
    )
    callback = MagicMock()
    state = _make_state(
        dto=_make_dto(),
        callback=callback,
        prompt=SimpleNamespace(messages=[system_message]),
    )
    return pipeline, state, system_message, callback


def test_assess_answer_extracts_json_verdict_from_noisy_response():
    pipeline, state, _msg, _cb = _assess_answer_state(
        'Sure thing! {"verdict": "SUSPICIOUS", "reasoning": "Wrong."} Thanks.'
    )

    pipeline._assess_answer(state)

    assert pipeline.verdict.verdict == "SUSPICIOUS"
    assert pipeline.verdict.reasoning == "Wrong."


def test_assess_answer_replaces_verdict_placeholder_with_escaped_braces():
    pipeline, state, system_message, _cb = _assess_answer_state(
        '{"verdict": "NEXT_QUESTION", "reasoning": "Vague."}'
    )

    pipeline._assess_answer(state)

    rendered = system_message.prompt.template
    assert VERDICT_DEPENDENT not in rendered
    # Braces from the rendered verdict template must be doubled so LangChain
    # does not try to interpret them as template variables.
    assert "{{question}}" in rendered
    assert "prefix" in rendered and "suffix" in rendered


def test_assess_answer_reports_error_on_malformed_json():
    pipeline, state, _msg, callback = _assess_answer_state("not json at all")

    pipeline._assess_answer(state)

    callback.fail.assert_called_once_with("Assessing answer failed.")
    assert pipeline.verdict is None


def test_assess_answer_tracks_tokens_when_available():
    pipeline, state, _msg, _cb = _assess_answer_state(
        '{"verdict": "UNSUSPICIOUS", "reasoning": "Good."}'
    )
    pipeline.assess_user_answer_pipeline.tokens = ["assess-token"]
    pipeline._track_tokens = MagicMock()

    pipeline._assess_answer(state)

    pipeline._track_tokens.assert_called_once_with(state, ["assess-token"])


# --------------------------------------------------------------------------
# assemble_prompt_with_history
# --------------------------------------------------------------------------


def test_assemble_prompt_with_history_clears_history_when_not_needed():
    pipeline = _make_pipeline()
    pipeline.chat_history_needed = False
    state = _make_state(message_history=["not empty"])

    with patch(
        "iris.pipeline.abstract_agent_pipeline.AbstractAgentPipeline.assemble_prompt_with_history",
        return_value="prompt",
    ) as super_call:
        pipeline.assemble_prompt_with_history(state, "system prompt")

    assert state.message_history == []
    super_call.assert_called_once_with(state, "system prompt")


def test_assemble_prompt_with_history_keeps_history_when_needed():
    pipeline = _make_pipeline()
    pipeline.chat_history_needed = True
    state = _make_state(message_history=["kept"])

    with patch(
        "iris.pipeline.abstract_agent_pipeline.AbstractAgentPipeline.assemble_prompt_with_history",
        return_value="prompt",
    ):
        pipeline.assemble_prompt_with_history(state, "system prompt")

    assert state.message_history == ["kept"]


# --------------------------------------------------------------------------
# __call__
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "event,expected_chat_history_needed",
    [
        (None, True),
        ("", True),
        ("BUILD_WITH_POINTS", True),
        ("FIRST_QUESTION", False),
        ("TAB_DEFOCUS", False),
        ("TIMER_RAN_OUT", False),
        ("USER_STARTS_QUIZ", False),
    ],
)
def test_call_sets_chat_history_needed_per_event(event, expected_chat_history_needed):
    pipeline = _make_pipeline()
    dto = _make_dto()
    variant = MagicMock()
    callback = MagicMock()

    with patch(
        "iris.pipeline.abstract_agent_pipeline.AbstractAgentPipeline.__call__"
    ) as super_call:
        pipeline(dto, variant, callback, event)

    assert pipeline.event == event
    assert pipeline.chat_history_needed == expected_chat_history_needed
    super_call.assert_called_once_with(dto, variant, callback)


def test_call_reports_error_when_super_call_raises():
    pipeline = _make_pipeline()
    dto = _make_dto()
    variant = MagicMock()
    callback = MagicMock()

    with patch(
        "iris.pipeline.abstract_agent_pipeline.AbstractAgentPipeline.__call__",
        side_effect=RuntimeError("boom"),
    ):
        pipeline(dto, variant, callback, None)

    callback.fail.assert_called_once()
