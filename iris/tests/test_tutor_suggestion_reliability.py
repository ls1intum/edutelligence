import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.domain.status.activity_dto import ActivityKind, ActivityState
from iris.pipeline import tutor_suggestion_pipeline as tutor_module
from iris.pipeline.shared.activity_tracker import ActivityTracker
from iris.pipeline.tutor_suggestion_pipeline import TutorSuggestionPipeline
from iris.web.status.status_update import TutorSuggestionCallback


def _message(role: IrisMessageRole, text: str) -> PyrisMessage:
    return PyrisMessage(
        sender=role,
        contents=[TextMessageContentDTO(textContent=text)],
    )


def _state(messages, *, result=None):
    return SimpleNamespace(
        message_history=messages,
        dto=SimpleNamespace(chat_history=messages),
        callback=Mock(),
        result=result,
    )


def _programming_state(feedbacks):
    state = _state([])
    state.db = Mock()
    state.activity_tracker = ActivityTracker(lambda *_: None)
    state.dto.course = SimpleNamespace(id=7, name="Programming")
    state.dto.post = SimpleNamespace(
        content="My assessed attempt still fails a test.", user_id=11, answers=[]
    )
    state.dto.programming_exercise = SimpleNamespace(problem_statement=None)
    state.dto.text_exercise = None
    state.dto.submission = SimpleNamespace(
        latest_result=SimpleNamespace(feedbacks=feedbacks), repository={}
    )
    state.dto.settings = None
    return state


@pytest.mark.parametrize(
    "regeneration_text",
    [
        "Please revise the suggestions and make them more concrete.",
        "Could you generate an alternative version?",
        "Bitte überarbeite die Vorschläge und formuliere sie kürzer.",
    ],
)
def test_regeneration_is_detected_after_an_artifact(regeneration_text):
    messages = [
        _message(IrisMessageRole.ARTIFACT, "Previous suggestions"),
        _message(IrisMessageRole.USER, regeneration_text),
    ]

    assert TutorSuggestionPipeline().is_regeneration_by_user_requested(_state(messages))


def test_artifact_followed_by_an_explanatory_question_is_not_regeneration():
    messages = [
        _message(IrisMessageRole.ARTIFACT, "Previous suggestions"),
        _message(IrisMessageRole.USER, "Why is the second point relevant?"),
    ]

    assert not TutorSuggestionPipeline().is_regeneration_by_user_requested(
        _state(messages)
    )


def test_regeneration_prompt_requires_retrieval_and_a_materially_new_artifact():
    messages = [
        _message(IrisMessageRole.ARTIFACT, "Previous suggestions"),
        _message(IrisMessageRole.USER, "Please revise this."),
    ]
    state = _state(messages)
    state.allow_lecture_tool = False
    state.allow_faq_tool = False
    state.suggestion_available = True
    state.regeneration_requested = True
    state.previous_artifact = "Previous suggestions"
    state.dto.course = SimpleNamespace(name="Software Engineering")
    state.dto.post = SimpleNamespace(
        content="A student needs help.", user_id=11, answers=[]
    )
    state.dto.programming_exercise = None
    state.dto.text_exercise = None

    prompt = TutorSuggestionPipeline().build_system_message(state)

    assert "previous artifact has been explicitly retrieved" in prompt
    assert "Previous suggestions" in prompt
    assert "materially different in substance" in prompt
    assert "without an acknowledgement or other meta-commentary" in prompt
    assert '"suggestions"' in prompt


def test_prepare_state_deterministically_retrieves_the_artifact(monkeypatch):
    monkeypatch.setattr(tutor_module, "should_allow_lecture_tool", lambda *_: False)
    monkeypatch.setattr(tutor_module, "should_allow_faq_tool", lambda *_: False)
    messages = [
        _message(IrisMessageRole.ARTIFACT, "Previous suggestions"),
        _message(IrisMessageRole.USER, "Please revise this."),
    ]
    state = _state(messages)
    state.db = Mock()
    state.dto.course = SimpleNamespace(id=7)
    state.activity_tracker = Mock()
    state.activity_tracker.start.return_value = "activity-1"

    TutorSuggestionPipeline().prepare_state(state)

    assert state.previous_artifact == "Previous suggestions"
    state.activity_tracker.start.assert_called_once_with(
        ActivityKind.TOOL, "get_last_artifact"
    )
    state.activity_tracker.finish.assert_called_once_with("activity-1")


def test_regeneration_does_not_expose_the_preflighted_artifact_tool(monkeypatch):
    messages = [
        _message(IrisMessageRole.ARTIFACT, "Previous suggestions"),
        _message(IrisMessageRole.USER, "Please revise this."),
    ]
    state = _state(messages)
    state.allow_lecture_tool = False
    state.allow_faq_tool = False
    state.suggestion_available = True
    state.regeneration_requested = True
    state.dto.course = SimpleNamespace(id=7, name="Software Engineering")
    state.dto.post = SimpleNamespace(
        content="A student needs help.", user_id=11, answers=[]
    )
    state.dto.programming_exercise = None
    state.dto.text_exercise = None
    state.dto.settings = None
    state.dto.submission = None
    last_artifact_factory = Mock(
        side_effect=AssertionError("artifact was already retrieved during preflight")
    )

    def course_details_tool():
        return {"name": "Software Engineering"}

    monkeypatch.setattr(
        tutor_module, "create_tool_get_last_artifact", last_artifact_factory
    )
    monkeypatch.setattr(
        tutor_module,
        "create_tool_get_simple_course_details",
        lambda *_: course_details_tool,
    )

    tools = TutorSuggestionPipeline().get_tools(state)

    last_artifact_factory.assert_not_called()
    assert tools == [course_details_tool]


def test_programming_feedback_is_retrieved_tracked_and_injected(monkeypatch):
    monkeypatch.setattr(tutor_module, "should_allow_lecture_tool", lambda *_: False)
    monkeypatch.setattr(tutor_module, "should_allow_faq_tool", lambda *_: False)
    feedbacks = [SimpleNamespace(text="The empty input assertion failed")]
    state = _programming_state(feedbacks)
    secret = "sk-" + "example-value-not-real"  # pragma: allowlist secret

    def create_feedback_tool(*_args):
        def get_feedbacks():
            return f"Case: handlesEmptyInput. Info: expected [] API_KEY={secret}"

        return get_feedbacks

    factory = Mock(side_effect=create_feedback_tool)
    monkeypatch.setattr(tutor_module, "create_tool_get_feedbacks", factory)
    pipeline = TutorSuggestionPipeline()

    pipeline.prepare_state(state)
    prompt = pipeline.build_system_message(state)

    activities, _ = state.activity_tracker.snapshot()
    assert [(item.name, item.state) for item in activities] == [
        ("get_feedbacks", ActivityState.FINISHED)
    ]
    assert "AUTHORITATIVE ARTEMIS AUTOMATED FEEDBACK" in prompt
    assert "handlesEmptyInput" in prompt
    assert "expected []" in prompt
    assert secret not in prompt
    assert "[REDACTED_API_KEY]" in prompt
    assert "untrusted data" in prompt


def test_absent_programming_feedback_does_not_run_or_inject_tool(monkeypatch):
    monkeypatch.setattr(tutor_module, "should_allow_lecture_tool", lambda *_: False)
    monkeypatch.setattr(tutor_module, "should_allow_faq_tool", lambda *_: False)
    forbidden = Mock(side_effect=AssertionError("feedback tool was constructed"))
    monkeypatch.setattr(tutor_module, "create_tool_get_feedbacks", forbidden)
    state = _programming_state([])
    pipeline = TutorSuggestionPipeline()

    pipeline.prepare_state(state)
    prompt = pipeline.build_system_message(state)

    forbidden.assert_not_called()
    assert state.activity_tracker.snapshot()[0] == []
    assert "AUTHORITATIVE ARTEMIS AUTOMATED FEEDBACK" not in prompt


def test_failed_feedback_preflight_is_visible_safe_and_not_retried(monkeypatch):
    monkeypatch.setattr(tutor_module, "should_allow_lecture_tool", lambda *_: False)
    monkeypatch.setattr(tutor_module, "should_allow_faq_tool", lambda *_: False)
    state = _programming_state([SimpleNamespace(text="A test failed")])

    def create_feedback_tool(*_args):
        def get_feedbacks():
            raise RuntimeError("temporary feedback failure")

        return get_feedbacks

    factory = Mock(side_effect=create_feedback_tool)
    monkeypatch.setattr(tutor_module, "create_tool_get_feedbacks", factory)
    pipeline = TutorSuggestionPipeline()

    pipeline.prepare_state(state)

    activities, _ = state.activity_tracker.snapshot()
    assert [(item.name, item.state) for item in activities] == [
        ("get_feedbacks", ActivityState.FAILED)
    ]
    assert state.automated_feedback_evidence is None
    assert state.automated_feedback_preflighted

    # The same failing source is not exposed to the model for a duplicate call.
    state.allow_lecture_tool = False
    state.allow_faq_tool = False
    monkeypatch.setattr(
        tutor_module,
        "create_tool_get_additional_exercise_details",
        lambda *_: lambda: {},
    )
    monkeypatch.setattr(
        tutor_module, "create_tool_get_submission_details", lambda *_: lambda: {}
    )
    monkeypatch.setattr(
        tutor_module,
        "create_tool_get_build_logs_analysis",
        lambda *_: lambda: "",
    )
    monkeypatch.setattr(
        tutor_module, "create_tool_get_simple_course_details", lambda *_: lambda: {}
    )
    tools = pipeline.get_tools(state)
    assert factory.call_count == 1
    assert all(tool.__name__ != "get_feedbacks" for tool in tools)


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        json.dumps({"suggestions": []}),
        json.dumps({"reply": "", "suggestions": ""}),
    ],
)
def test_invalid_or_empty_structured_output_fails_closed(raw):
    state = _state([], result=raw)

    with pytest.raises(ValueError):
        TutorSuggestionPipeline().post_agent_hook(state)

    state.callback.finish.assert_not_called()


@pytest.mark.parametrize(
    "raw",
    [
        '```json\n{"reply": "Grounded answer."}\n```',
        "Result: {'reply': 'Grounded answer.',}",
    ],
)
def test_common_structured_output_wrappers_are_repaired_without_a_model_retry(raw):
    messages = [_message(IrisMessageRole.USER, "Why is this relevant?")]
    state = _state(messages, result=raw)
    state.regeneration_requested = False

    TutorSuggestionPipeline().post_agent_hook(state)

    state.callback.finish.assert_called_once_with(
        result="Grounded answer.", tokens=[], artifact=None
    )


def test_legacy_question_list_is_normalized_to_a_safe_artifact():
    state = _state(
        [],
        result=json.dumps(
            {"questions": ["Inspect the first message", "Compare x < y"]}
        ),
    )

    TutorSuggestionPipeline().post_agent_hook(state)

    state.callback.finish.assert_called_once_with(
        result=None,
        tokens=[],
        artifact=(
            "<ul><li>Inspect the first message</li>" "<li>Compare x &lt; y</li></ul>"
        ),
    )


def test_regeneration_rejects_cosmetic_reformatting_of_previous_artifact():
    previous = "Ask the student to inspect the loop boundary."
    messages = [
        _message(IrisMessageRole.ARTIFACT, previous),
        _message(IrisMessageRole.USER, "Please revise it."),
    ]
    state = _state(
        messages,
        result=json.dumps(
            {
                "suggestions": (
                    "<ul><li>Ask the student to inspect the loop boundary.</li></ul>"
                )
            }
        ),
    )
    state.regeneration_requested = True

    with pytest.raises(ValueError, match="repeat"):
        TutorSuggestionPipeline().post_agent_hook(state)

    state.callback.finish.assert_not_called()


def test_regeneration_delivers_a_materially_new_nonempty_artifact():
    messages = [
        _message(
            IrisMessageRole.ARTIFACT,
            "Ask the student to inspect the loop boundary.",
        ),
        _message(IrisMessageRole.USER, "Please offer another approach."),
    ]
    suggestions = (
        "<ul><li>Ask the student to compare the failing test with the stated "
        "input contract.</li><li>Invite them to trace one minimal example by "
        "hand.</li></ul>"
    )
    state = _state(
        messages,
        result=json.dumps({"reply": "Updated.", "suggestions": suggestions}),
    )
    state.regeneration_requested = True

    TutorSuggestionPipeline().post_agent_hook(state)

    state.callback.finish.assert_called_once_with(
        result=None, tokens=[], artifact=suggestions
    )


def test_regeneration_terminal_payload_exposes_the_replacement_artifact():
    messages = [
        _message(
            IrisMessageRole.ARTIFACT,
            "Ask the student to inspect the loop boundary.",
        ),
        _message(IrisMessageRole.USER, "Please offer another approach."),
    ]
    suggestions = (
        "<ul><li>Ask the student to trace a minimal failing input.</li>"
        "<li>Tell them to compare each state transition.</li></ul>"
    )
    state = _state(
        messages,
        result=json.dumps(
            {"reply": "I created another version.", "suggestions": suggestions}
        ),
    )
    state.regeneration_requested = True
    callback = TutorSuggestionCallback("run-1", "https://callback.invalid")
    delivery = Mock(return_value=True)
    callback.on_status_update = delivery
    state.callback = callback

    TutorSuggestionPipeline().post_agent_hook(state)

    delivery.assert_called_once()
    payload = callback.status.model_dump(by_alias=True)
    assert payload["runState"] == "FINISHED"
    assert payload["result"] is None
    assert payload["artifact"] == suggestions


def test_regeneration_meta_reply_without_an_artifact_fails_closed():
    messages = [
        _message(
            IrisMessageRole.ARTIFACT,
            "Ask the student to inspect the loop boundary.",
        ),
        _message(IrisMessageRole.USER, "Please offer another approach."),
    ]
    state = _state(
        messages,
        result=json.dumps({"reply": "Got it. I will use a tiny trace."}),
    )
    state.regeneration_requested = True

    with pytest.raises(ValueError, match="did not contain suggestions"):
        TutorSuggestionPipeline().post_agent_hook(state)

    state.callback.finish.assert_not_called()


def test_tutor_question_can_return_a_reply_without_creating_an_artifact():
    messages = [_message(IrisMessageRole.USER, "Why is this relevant?")]
    state = _state(messages, result=json.dumps({"reply": "Because it is grounded."}))
    state.regeneration_requested = False

    TutorSuggestionPipeline().post_agent_hook(state)

    state.callback.finish.assert_called_once_with(
        result="Because it is grounded.", tokens=[], artifact=None
    )
