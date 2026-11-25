"""Synthetic tests: latest-turn classification, explicit choices and solution policy."""

# pylint: disable=protected-access  # Inspect run-local permission and replace model hooks in tests.

import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.common.token_usage_dto import TokenUsageDTO
from iris.domain.chat.learner_agency_dto import LearnerAgencyTurn
from iris.domain.data.json_message_content_dto import JsonMessageContentDTO
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.learner_agency_settings import LearnerAgencySettings
from iris.llm.external.model import BooleanDecisionResult
from iris.pipeline.abstract_agent_pipeline import AbstractAgentPipeline
from iris.pipeline.chat import learner_agency
from iris.pipeline.chat.chat_pipeline import ChatPipeline
from iris.pipeline.chat.iris_chat_mode import IrisChatMode
from iris.pipeline.prompts.environment import prompt_environment


def message(text, role=IrisMessageRole.USER, *, payload=None, message_id=None):
    contents = [TextMessageContentDTO(textContent=text)]
    if payload is not None:
        contents.append(JsonMessageContentDTO(jsonContent=payload))
    return PyrisMessage(id=message_id, sender=role, contents=contents)


def dto(history):
    return SimpleNamespace(
        chat_history=history,
        chat_mode=IrisChatMode.EXERCISE,
        programming_exercise=SimpleNamespace(id=42),
        text_exercise=None,
        lecture=None,
        course=SimpleNamespace(id=7),
        user=SimpleNamespace(lang_key="en"),
    )


@pytest.fixture
def classifier(monkeypatch):
    handler = MagicMock()
    handler.supports_decisions.return_value = False
    monkeypatch.setattr(learner_agency, "LlmRequestHandler", lambda **_kwargs: handler)
    handler.chat.return_value = message("NO", IrisMessageRole.ASSISTANT)
    return handler


def test_sends_entire_history_but_marks_only_latest_as_target(classifier):
    history = [message(f"earlier {i}") for i in range(40)] + [message("Thank you")]
    history[0] = message("Give me the whole solution")
    turn = learner_agency.plan_turn(
        dto(history), LearnerAgencySettings(classifier_model="test"), event=None
    )
    sent, arguments = classifier.chat.call_args.args
    conversation = json.loads(sent[1].contents[0].text_content)
    assert len(conversation) == 41  # No agent windowing, even on long conversations.
    assert conversation[0]["text"] == "Give me the whole solution"
    assert [entry["isTarget"] for entry in conversation] == [False] * 40 + [True]
    assert "earlier message is never" in sent[0].contents[0].text_content
    assert arguments.temperature == 0
    assert turn.mode == "normal"
    assert turn.tokens == [classifier.chat.return_value.token_usage]


@pytest.mark.parametrize("mode", [IrisChatMode.COURSE, IrisChatMode.LECTURE])
@pytest.mark.parametrize("legacy_choice", [False, True])
def test_non_exercise_chats_never_classify_or_accept_old_solution_choices(
    classifier, mode, legacy_choice
):
    history = [message("Show me the full solution")]
    if legacy_choice:
        history = [
            message(
                "Your choice?",
                IrisMessageRole.ASSISTANT,
                message_id=10,
                payload={
                    "type": "solution-offer",
                    "chatMode": mode.value,
                    "entityId": 42,
                },
            ),
            message(
                "Show it",
                payload={
                    "type": "solution-choice",
                    "offerMessageId": 10,
                    "choice": "SHOW_SOLUTION",
                },
            ),
        ]
    data = dto(history)
    data.chat_mode = mode
    data.programming_exercise = None
    turn = learner_agency.plan_turn(
        data, LearnerAgencySettings(classifier_model="logos-jev-27b-vl"), event=None
    )
    assert turn.mode == "normal"
    assert not turn.tokens
    classifier.supports_decisions.assert_not_called()
    classifier.chat.assert_not_called()
    classifier.decide.assert_not_called()


@pytest.mark.parametrize("mode", [IrisChatMode.EXERCISE, IrisChatMode.TEXT_EXERCISE])
def test_both_exercise_chat_types_can_offer_solutions(classifier, mode):
    data = dto([message("Show the solution")])
    data.chat_mode = mode
    if mode == IrisChatMode.TEXT_EXERCISE:
        data.text_exercise = data.programming_exercise
        data.programming_exercise = None
    classifier.chat.return_value = message("YES")
    turn = learner_agency.plan_turn(
        data, LearnerAgencySettings(classifier_model="test"), event=None
    )
    assert turn.mode == "offer"
    assert learner_agency.context_offer(data).chat_mode == mode.value
    assert learner_agency.context_offer(data).entity_id == 42


@pytest.mark.parametrize(
    "probability, expected", [(0.9, "offer"), (0.1, "normal"), (0.5, "normal")]
)
def test_native_decision_uses_latest_message_marker_and_probability(
    classifier, probability, expected
):

    classifier.supports_decisions.return_value = True
    classifier.decide.return_value = BooleanDecisionResult(
        probability=probability, token_usage=TokenUsageDTO(model="autotrust/JEV-27B-VL")
    )
    data = dto(
        [
            message("Show the solution"),
            message("A previous answer", IrisMessageRole.ASSISTANT),
            message("Thanks"),
        ]
    )
    turn = learner_agency.plan_turn(
        data, LearnerAgencySettings(classifier_model="logos-jev-27b-vl"), event=None
    )
    assert turn.mode == expected
    classifier.chat.assert_not_called()
    state, instructions = classifier.decide.call_args.args
    assert [entry["isTarget"] for entry in json.loads(state)] == [False, False, True]
    assert "earlier message is never" in instructions
    assert "Reply with exactly" not in instructions
    assert turn.tokens == [classifier.decide.return_value.token_usage]


def test_native_decision_threshold_is_configurable(classifier):

    classifier.supports_decisions.return_value = True
    classifier.decide.return_value = BooleanDecisionResult(
        probability=0.7, token_usage=TokenUsageDTO()
    )
    turn = learner_agency.plan_turn(
        dto([message("Solve it")]),
        LearnerAgencySettings(
            classifier_model="logos-jev-27b-vl", classifier_threshold=0.8
        ),
        event=None,
    )
    assert turn.mode == "normal"


def test_later_requests_can_trigger_another_offer(classifier):
    classifier.chat.side_effect = [message("YES"), message("NO"), message("YES")]
    history = []
    modes = []
    for text in ["Give me the solution", "Thanks", "Now solve part b"]:
        history.append(message(text))
        modes.append(
            learner_agency.plan_turn(
                dto(history), LearnerAgencySettings(classifier_model="test"), event=None
            ).mode
        )
        history.append(message("Previous answer", IrisMessageRole.ASSISTANT))
    assert modes == ["offer", "normal", "offer"]


@pytest.mark.parametrize(
    "choice, expected", [("TRY_MYSELF", "hint"), ("SHOW_SOLUTION", "solution")]
)
def test_valid_choices_bypass_classifier(classifier, choice, expected):
    offer = learner_agency.context_offer(dto([])).model_dump(by_alias=True)
    history = [
        message("Solve it"),
        message(
            "Your choice?", IrisMessageRole.ASSISTANT, message_id=10, payload=offer
        ),
        message(
            "My choice",
            payload={"type": "solution-choice", "offerMessageId": 10, "choice": choice},
        ),
    ]
    assert (
        learner_agency.plan_turn(
            dto(history), LearnerAgencySettings(classifier_model="test"), event=None
        ).mode
        == expected
    )
    classifier.chat.assert_not_called()


@pytest.mark.parametrize(
    "invalid",
    [
        "wrong-context",
        "wrong-offer",
        "intervening-message",
        "user-offer",
        "unknown-choice",
    ],
)
def test_invalid_choices_never_enable_solutions(classifier, invalid):
    offer = learner_agency.context_offer(dto([])).model_dump(by_alias=True)
    action = {
        "type": "solution-choice",
        "offerMessageId": 10,
        "choice": "SHOW_SOLUTION",
    }
    if invalid == "wrong-context":
        offer["entityId"] = 99
    if invalid == "wrong-offer":
        action["offerMessageId"] = 12
    if invalid == "unknown-choice":
        action["choice"] = "INVALID"
    history = [
        message("Your choice?", IrisMessageRole.ASSISTANT, message_id=10, payload=offer)
    ]
    if invalid == "user-offer":
        history[0].sender = IrisMessageRole.USER
    if invalid == "intervening-message":
        history.append(message("I changed my mind"))
    history.append(message("My choice", payload=action))
    assert (
        learner_agency.plan_turn(
            dto(history), LearnerAgencySettings(classifier_model="test"), event=None
        ).mode
        == "normal"
    )
    classifier.chat.assert_not_called()


def test_selection_does_not_grant_permission_for_future_turns(classifier):
    history = [
        message("Delivered solution", IrisMessageRole.ASSISTANT),
        message("Why does line 4 use a loop?"),
    ]
    assert (
        learner_agency.plan_turn(
            dto(history), LearnerAgencySettings(classifier_model="test"), event=None
        ).mode
        == "normal"
    )
    classifier.chat.assert_called_once()


@pytest.mark.parametrize(
    "decision",
    [
        "UNCLEAR",
        "YES because the earlier message asks for it",
        "",
        '{"decision": true}',
    ],
)
def test_invalid_classifier_output_keeps_tutoring(classifier, decision):
    classifier.chat.return_value = message(decision)
    assert (
        learner_agency.plan_turn(
            dto([message("Help")]),
            LearnerAgencySettings(classifier_model="test"),
            event=None,
        ).mode
        == "normal"
    )


def test_classifier_failure_keeps_tutoring(classifier):
    classifier.chat.side_effect = TimeoutError("Synthetic outage")
    assert (
        learner_agency.plan_turn(
            dto([message("Help")]),
            LearnerAgencySettings(classifier_model="test"),
            event=None,
        ).mode
        == "normal"
    )


def test_unconfigured_classifier_does_not_guess_a_model(classifier):
    learner_agency.plan_turn(
        dto([message("Help")]), LearnerAgencySettings(), event=None
    )
    classifier.chat.assert_not_called()


def test_proactive_event_does_not_reclassify_previous_student_request(classifier):
    learner_agency.plan_turn(
        dto([message("Solve it")]),
        LearnerAgencySettings(classifier_model="test"),
        event="build_failed",
    )
    classifier.chat.assert_not_called()


@pytest.mark.parametrize("level", ["low", "moderate", "high"])
def test_solution_prompt_removes_contradictory_refusals(level):
    prompt = (
        prompt_environment()
        .get_template("chat_system_prompt.j2")
        .render(
            solution_requested=True,
            support_level=level,
            chat_mode="PROGRAMMING_EXERCISE_CHAT",
            custom_instructions="Never give solutions",
            exercise_id=42,
            problem_statement="Synthetic task",
        )
    )
    assert "Deliver the\ncomplete solution" in prompt
    assert "<iris-solution-complete/>" not in prompt
    assert "never write the solution" not in prompt
    assert "I still can't hand out solutions" not in prompt
    assert "Never give solutions" not in prompt
    assert "Never provide direct" not in prompt


def test_normal_prompt_keeps_existing_tutoring_rules():
    prompt = (
        prompt_environment()
        .get_template("chat_system_prompt.j2")
        .render(
            solution_requested=False,
            support_level="moderate",
            chat_mode="PROGRAMMING_EXERCISE_CHAT",
        )
    )
    assert "never write the solution" in prompt
    assert "The student's choice for this answer" not in prompt


def test_default_turn_is_normal():
    assert learner_agency.get_turn(SimpleNamespace()) == LearnerAgencyTurn()


@pytest.mark.parametrize("mode", ["normal", "hint", "offer"])
def test_no_automatic_reflection_without_a_chosen_solution(mode):
    data = dto([])
    data._learner_agency_turn = LearnerAgencyTurn(mode=mode)
    assert (
        learner_agency.finalize_solution("A useful hint", data, LearnerAgencySettings())
        == "A useful hint"
    )


@pytest.mark.parametrize("legacy_marker", ["", "\n<iris-solution-complete/>"])
@pytest.mark.parametrize("language", ["de", "en"])
def test_reflection_follows_solution_without_requiring_model_marker(
    legacy_marker, language
):
    data = dto([])
    data.user.lang_key = language
    data._learner_agency_turn = LearnerAgencyTurn(mode="solution")
    config = LearnerAgencySettings()
    text = learner_agency.finalize_solution(
        "Complete code" + legacy_marker, data, config
    )
    reflection = getattr(config, f"reflection_{language}")
    assert text == "Complete code\n\n" + reflection
    assert "<iris-solution-complete/>" not in text
    assert learner_agency.finalize_solution(text, data, config) == text


@pytest.mark.parametrize("answer", ["", "  ", "<iris-solution-complete/>"])
def test_empty_answer_does_not_produce_reflection_on_its_own(answer):
    data = dto([])
    data._learner_agency_turn = LearnerAgencyTurn(mode="solution")
    assert not learner_agency.finalize_solution(
        answer, data, LearnerAgencySettings()
    ).strip()


def test_empty_reflection_configuration_is_respected():
    data = dto([])
    data._learner_agency_turn = LearnerAgencyTurn(mode="solution")
    assert (
        learner_agency.finalize_solution(
            "Complete code", data, LearnerAgencySettings(reflection_en="")
        )
        == "Complete code"
    )


def test_offer_is_delivered_without_running_the_chat_model(monkeypatch):

    parent = MagicMock()
    monkeypatch.setattr(AbstractAgentPipeline, "__call__", parent)
    monkeypatch.setattr(
        "iris.pipeline.chat.chat_pipeline.plan_turn",
        lambda *_args, **_kwargs: LearnerAgencyTurn(mode="offer"),
    )
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline.chat_mode = IrisChatMode.EXERCISE
    callback = MagicMock()
    pipeline(dto([message("Solve it")]), SimpleNamespace(), callback)
    parent.assert_not_called()
    callback.send_result.assert_called_once()
    assert callback.send_result.call_args.kwargs["solution_offer"].entity_id == 42
    callback.finish.assert_called_once()


@pytest.mark.parametrize("mode", [IrisChatMode.EXERCISE, IrisChatMode.TEXT_EXERCISE])
def test_solution_skips_the_guide_and_delivers_reflection_without_model_marker(
    monkeypatch, mode
):

    monkeypatch.setattr(
        "iris.pipeline.chat.chat_pipeline.mcq_post_agent_hook", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        "iris.pipeline.chat.chat_pipeline.reply_language", lambda *_args: "en"
    )
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline.chat_mode = mode
    pipeline.mcq_pipeline = MagicMock()
    pipeline._refine_response = MagicMock(
        side_effect=AssertionError("Guide must not rewrite a chosen solution")
    )
    pipeline._add_citations = lambda _state, result: result
    pipeline._generate_session_title = MagicMock(return_value=None)
    pipeline._generate_suggestions = MagicMock()
    data = dto([])
    data.chat_mode = mode
    data._learner_agency_turn = LearnerAgencyTurn(mode="solution")
    state = SimpleNamespace(
        dto=data,
        result="Complete code",
        start_time=time.perf_counter(),
        query_text="Show the solution",
        callback=MagicMock(),
        tokens=[],
        pending_context_switch=None,
        activity_tracker=MagicMock(),
    )
    state.activity_tracker.authoritative_snapshot.return_value = ([], 0)
    pipeline.post_agent_hook(state)
    pipeline._refine_response.assert_not_called()
    state.callback.fail.assert_not_called()
    delivered = state.callback.send_result.call_args.args[0]
    assert "Complete code" in delivered
    assert "Would you like to reflect" in delivered
    assert "<iris-solution-complete/>" not in delivered


def test_local_ai_selection_does_not_send_history_to_cloud_classifier(classifier):
    data = dto([message("Help")])
    data.settings = SimpleNamespace(is_local=lambda: True)
    learner_agency.plan_turn(
        data, LearnerAgencySettings(classifier_model="cloud-classifier"), event=None
    )
    classifier.chat.assert_not_called()


@pytest.mark.parametrize("mode", ["normal", "hint", "offer"])
def test_reference_solution_is_unavailable_outside_solution_turns(mode):
    data = dto([])
    data.programming_exercise.solution_repository = {"Main.java": "INSTRUCTOR CODE"}
    data._learner_agency_turn = LearnerAgencyTurn(mode=mode)
    assert learner_agency.reference_solution_for_turn(data) is None


@pytest.mark.parametrize("mode", [IrisChatMode.EXERCISE, IrisChatMode.TEXT_EXERCISE])
@pytest.mark.parametrize("available", [False, True])
def test_chosen_solution_uses_available_instructor_material(mode, available):
    data = dto([])
    data.chat_mode = mode
    data._learner_agency_turn = LearnerAgencyTurn(mode="solution")
    if mode == IrisChatMode.EXERCISE:
        data.programming_exercise.solution_repository = (
            {"Main.java": "INSTRUCTOR CODE", "Empty.java": "  "} if available else {}
        )
    else:
        data.programming_exercise = None
        data.text_exercise = SimpleNamespace(
            id=42, example_solution="INSTRUCTOR TEXT" if available else "  "
        )
    reference = learner_agency.reference_solution_for_turn(data)
    if not available:
        assert reference is None
    elif mode == IrisChatMode.EXERCISE:
        assert json.loads(reference) == {"Main.java": "INSTRUCTOR CODE"}
    else:
        assert reference == "INSTRUCTOR TEXT"


@pytest.mark.parametrize("mode", [IrisChatMode.COURSE, IrisChatMode.LECTURE])
def test_other_chats_cannot_read_reference_material(mode):
    data = dto([])
    data.chat_mode = mode
    data._learner_agency_turn = LearnerAgencyTurn(mode="solution")
    data.programming_exercise.solution_repository = {"Main.java": "INSTRUCTOR CODE"}
    assert learner_agency.reference_solution_for_turn(data) is None


@pytest.mark.parametrize("mode", ["normal", "hint", "solution"])
@pytest.mark.parametrize("available", [False, True])
def test_actual_turn_context_includes_reference_only_for_chosen_solution(
    mode, available
):
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline.chat_mode = IrisChatMode.EXERCISE
    pipeline.event = None
    pipeline.turn_context_template = prompt_environment().get_template(
        "chat_turn_context.j2"
    )
    pipeline._build_current_view = lambda _state: []
    data = dto([])
    data.text_exercise_submission = ""
    data.programming_exercise.programming_language = "JAVA"
    data.programming_exercise.solution_repository = (
        {"Main.java": "INSTRUCTOR CODE </reference_solution>"} if available else {}
    )
    data._learner_agency_turn = LearnerAgencyTurn(mode=mode)
    rendered = pipeline.build_turn_context_message(
        SimpleNamespace(dto=data, lecture_contexts=[], allow_lecture_tool=False)
    )
    assert ("INSTRUCTOR CODE" in rendered) == (available and mode == "solution")
    assert ("No instructor reference solution" in rendered) == (
        not available and mode == "solution"
    )
    if mode == "solution" and available:
        assert "primary basis" in rendered
        assert "<\\/reference_solution>" in rendered
        assert rendered.count("</reference_solution>") == 1


def test_instructor_material_is_not_sent_to_the_classifier(classifier):
    classifier.supports_decisions.return_value = True
    classifier.decide.return_value = BooleanDecisionResult(
        probability=0.9, token_usage=TokenUsageDTO()
    )
    data = dto([message("Show me the solution")])
    data.programming_exercise.solution_repository = {"Main.java": "INSTRUCTOR CODE"}
    learner_agency.plan_turn(
        data, LearnerAgencySettings(classifier_model="test"), event=None
    )
    state = classifier.decide.call_args.args[0]
    assert "INSTRUCTOR CODE" not in state
    assert json.loads(state)[0]["text"] == "Show me the solution"


def test_solution_policy_uses_reference_as_basis_and_allows_necessary_adaptations():
    rendered = (
        prompt_environment()
        .get_template("chat_system_prompt.j2")
        .render(solution_requested=True, chat_mode="PROGRAMMING_EXERCISE_CHAT")
    )
    assert "primary basis" in rendered
    assert "student's existing code" in rendered
    assert "explain necessary changes" in rendered
