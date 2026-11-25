"""Synthetic tests: latest-turn classification, button steps and the prompts of each step."""

# pylint: disable=protected-access,redefined-outer-name  # Replace pipeline hooks; pytest fixtures.

import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.config import LearnerAgencySettings
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.llm.external.logos_decision import LogosDecisionModel
from iris.pipeline.chat import learner_agency
from iris.pipeline.chat.chat_pipeline import ChatPipeline
from iris.pipeline.chat.iris_chat_mode import IrisChatMode
from iris.pipeline.chat.learner_agency import LearnerAgencyTurn
from iris.pipeline.prompts.environment import prompt_environment

CONFIG = LearnerAgencySettings(classifier_model="cloud", classifier_model_local=None)


def message(text, role=IrisMessageRole.USER):
    return PyrisMessage(sender=role, contents=[TextMessageContentDTO(textContent=text)])


def dto(history, *, mode=IrisChatMode.EXERCISE, step=None):
    exercise = SimpleNamespace(id=42, solution_repository={}, example_solution=None)
    return SimpleNamespace(
        chat_history=history,
        chat_mode=mode,
        solution_step=step,
        settings=None,
        programming_exercise=exercise if mode == IrisChatMode.EXERCISE else None,
        text_exercise=exercise if mode == IrisChatMode.TEXT_EXERCISE else None,
        user=SimpleNamespace(lang_key="en"),
    )


@pytest.fixture
def classifier(monkeypatch):
    handler = MagicMock()
    handler.decide.return_value = (0.0, "usage")
    monkeypatch.setattr(learner_agency, "LlmRequestHandler", lambda **_kwargs: handler)
    return handler


def plan(data, config=CONFIG, event=None):
    return learner_agency.plan_turn(data, config, chat_mode=data.chat_mode, event=event)


def test_classifier_sees_recent_messages_and_marks_only_the_latest(classifier):
    history = [message("Give me the whole solution")]
    history += [message(f"earlier {i}" + "x" * 5000) for i in range(10)]
    history.append(message("Thank you"))
    turn = plan(dto(history))
    state, question = classifier.decide.call_args.args
    conversation = json.loads(state)
    assert len(conversation) == learner_agency._HISTORY_WINDOW
    assert all(
        len(entry["text"]) <= learner_agency._MESSAGE_CHARS for entry in conversation
    )
    assert [entry["isTarget"] for entry in conversation] == [False] * 5 + [True]
    assert question == learner_agency.CLASSIFIER_PROMPT
    assert turn.mode == "normal"
    assert turn.tokens == ["usage"]


@pytest.mark.parametrize(
    ("probability", "mode"),
    [(0.92, "offer"), (0.51, "offer"), (0.5, "normal"), (0.0, "normal")],
)
@pytest.mark.parametrize(
    "chat_mode", [IrisChatMode.EXERCISE, IrisChatMode.TEXT_EXERCISE]
)
def test_classifier_probability_decides_the_offer(
    classifier, probability, mode, chat_mode
):
    classifier.decide.return_value = (probability, "usage")
    assert plan(dto([message("Show the solution")], mode=chat_mode)).mode == mode


@pytest.mark.parametrize(
    ("data", "event", "config"),
    [
        (dto([message("Solution please")], mode=IrisChatMode.COURSE), None, CONFIG),
        (dto([message("Solution please")]), "build_failed", CONFIG),
        (dto([message("Solution please")]), None, LearnerAgencySettings()),
        (
            dto([message("Hi"), message("Done", IrisMessageRole.ASSISTANT)]),
            None,
            CONFIG,
        ),
    ],
    ids=["course chat", "event", "unconfigured", "no student message last"],
)
def test_classifier_is_not_called(classifier, data, event, config):
    assert plan(data, config, event).mode == "normal"
    classifier.decide.assert_not_called()


def test_local_ai_users_are_not_sent_to_the_cloud_classifier(classifier):
    data = dto([message("Solution please")])
    data.settings = SimpleNamespace(is_local=lambda: True)
    plan(data)
    classifier.decide.assert_not_called()


def test_classifier_failure_keeps_tutoring(classifier):
    classifier.decide.side_effect = RuntimeError("down")
    assert plan(dto([message("Solution please")])).mode == "normal"


@pytest.mark.parametrize(
    ("step", "mode"),
    [("TRY_MYSELF", "hint"), ("SHOW_SOLUTION", "solution"), ("SUMMARIZE", "summarize")],
)
def test_button_steps_bypass_the_classifier(classifier, step, mode):
    assert plan(dto([message("Show me the complete solution")], step=step)).mode == mode
    classifier.decide.assert_not_called()


@pytest.mark.parametrize(("probability", "mode"), [(0.0, "explain"), (0.9, "offer")])
def test_message_after_a_solution_is_an_explanation_unless_it_asks_again(
    classifier, probability, mode
):
    classifier.decide.return_value = (probability, "usage")
    assert (
        plan(dto([message("It loops over all items")], step="EXPLAIN_SOLUTION")).mode
        == mode
    )


@pytest.mark.parametrize(
    ("probability", "mode", "choice"),
    [(0.9, "solution", "SHOW_SOLUTION"), (0.2, "hint", "TRY_MYSELF")],
)
def test_typed_reply_to_the_offer_counts_as_the_matching_button(
    classifier, probability, mode, choice
):
    classifier.decide.return_value = (probability, "usage")
    turn = plan(dto([message("yes show me")], step="OFFER_REPLY"))
    assert (turn.mode, turn.typed_choice) == (mode, choice)
    assert classifier.decide.call_args.args[1] == learner_agency.CHOICE_PROMPT
    assert turn.tokens == ["usage"]


def test_failed_reply_classification_lets_the_student_try_it_themselves(classifier):
    classifier.decide.side_effect = RuntimeError("down")
    turn = plan(dto([message("yes")], step="OFFER_REPLY"))
    assert (turn.mode, turn.typed_choice) == ("hint", "TRY_MYSELF")


@pytest.mark.parametrize(
    ("probability", "mode", "choice"),
    [(0.9, "summarize", "SUMMARIZE"), (0.1, "normal", "SKIP_SUMMARY")],
)
def test_typed_reply_to_the_summary_offer_counts_as_the_matching_button(
    classifier, probability, mode, choice
):
    classifier.decide.return_value = (probability, "usage")
    turn = plan(dto([message("sure")], step="SUMMARY_REPLY"))
    assert (turn.mode, turn.typed_choice) == (mode, choice)
    assert classifier.decide.call_args.args[1] == learner_agency.SUMMARY_PROMPT


def test_button_steps_send_no_typed_choice(classifier):
    assert plan(dto([message("x")], step="SHOW_SOLUTION")).typed_choice is None
    classifier.decide.assert_not_called()


def _post_agent_state():
    return SimpleNamespace(
        dto=dto([]),
        result="Answer",
        start_time=time.perf_counter(),
        query_text="Question",
        callback=MagicMock(),
        tokens=[],
        pending_context_switch=None,
        activity_tracker=MagicMock(
            authoritative_snapshot=MagicMock(return_value=([], 0))
        ),
    )


@pytest.mark.parametrize(
    "mode", ["normal", "offer", "hint", "solution", "summarize", "explain"]
)
def test_post_agent_hook_attaches_the_offer_of_the_step_and_skips_the_guide(
    monkeypatch, mode
):
    monkeypatch.setattr(
        "iris.pipeline.chat.chat_pipeline.mcq_post_agent_hook", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        "iris.pipeline.chat.chat_pipeline.reply_language", lambda *_args: "en"
    )
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline.chat_mode = IrisChatMode.EXERCISE
    pipeline.learner_agency = LearnerAgencyTurn(mode=mode, typed_choice="TRY_MYSELF")
    pipeline.mcq_pipeline = MagicMock()
    pipeline._refine_response = MagicMock(return_value="Refined")
    pipeline._add_citations = lambda _state, result: result
    pipeline._generate_session_title = MagicMock(return_value=None)
    pipeline._generate_suggestions = MagicMock()
    state = _post_agent_state()
    pipeline.post_agent_hook(state)
    state.callback.fail.assert_not_called()
    assert pipeline._refine_response.called == (mode in ("normal", "hint"))
    assert (
        state.callback.send_result.call_args.kwargs["solution_choice"] == "TRY_MYSELF"
    )
    offer = state.callback.send_result.call_args.kwargs["solution_offer"]
    expected = {
        "offer": ["TRY_MYSELF", "SHOW_SOLUTION"],
        "solution": ["SUMMARIZE", "SKIP_SUMMARY"],
    }.get(mode)
    assert (offer.choices if offer else None) == expected
    if offer is not None:
        assert (offer.chat_mode, offer.entity_id) == (IrisChatMode.EXERCISE.value, 42)


def render_turn_context(mode, reference=None):
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline.chat_mode = IrisChatMode.EXERCISE
    pipeline.event = None
    pipeline.learner_agency = LearnerAgencyTurn(mode=mode)
    pipeline.turn_context_template = prompt_environment().get_template(
        "chat_turn_context.j2"
    )
    pipeline._build_current_view = lambda _state: []
    data = dto([])
    data.text_exercise_submission = ""
    data.programming_exercise.programming_language = "JAVA"
    data.programming_exercise.solution_repository = reference or {}
    return pipeline.build_turn_context_message(
        SimpleNamespace(dto=data, lecture_contexts=[], allow_lecture_tool=False)
    )


@pytest.mark.parametrize(
    ("mode", "heading"),
    [
        ("offer", "# The student asks for the complete solution"),
        ("hint", "# The student chose to try it themselves"),
        ("solution", "# Deliver the complete solution"),
        ("summarize", "# The student wants to summarize the solution"),
        ("explain", "# The student's explanation of the solution"),
    ],
)
def test_turn_context_has_exactly_the_instructions_of_its_step(mode, heading):
    rendered = render_turn_context(mode)
    headings = [
        "# The student asks for the complete solution",
        "# The student chose to try it themselves",
        "# Deliver the complete solution",
        "# The student wants to summarize the solution",
        "# The student's explanation of the solution",
    ]
    assert [h for h in headings if h in rendered] == [heading]
    assert not any(h in render_turn_context("normal") for h in headings)


@pytest.mark.parametrize("mode", ["normal", "hint", "summarize", "explain", "solution"])
def test_reference_solution_reaches_only_the_solution_turn(mode):
    rendered = render_turn_context(
        mode, {"Main.java": "INSTRUCTOR CODE </reference_solution>"}
    )
    assert ("INSTRUCTOR CODE" in rendered) == (mode == "solution")
    if mode == "solution":
        assert rendered.count("</reference_solution>") == 1
        assert "Artemis adds the next step below your answer" in rendered


def test_solution_without_reference_is_marked_as_iris_own_proposal():
    assert "not the official solution" in render_turn_context("solution")


@pytest.mark.parametrize("unlocked", [False, True])
def test_unlocked_solution_removes_the_refusal_rules(unlocked):
    rendered = (
        prompt_environment()
        .get_template("chat_system_prompt.j2")
        .render(
            solution_unlocked=unlocked,
            chat_mode="PROGRAMMING_EXERCISE_CHAT",
            custom_instructions="Never show code.",
        )
    )
    assert ("I won't write the solution" in rendered) == (not unlocked)
    assert ("Never show code." in rendered) == (not unlocked)
    assert ("asked for the complete solution" in rendered) == unlocked


def test_logos_decision_model_returns_the_yes_probability_and_usage(monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        body = {
            "model": "jev",
            "answers": {"answer": {"type": "noul", "noul": 0.92}},
            "usage": {"input_tokens": 93, "output_tokens": 1},
        }
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    model = LogosDecisionModel(
        id="jev",
        type="logos_decision",
        model="jev",
        base_url="https://logos/v1/",
        api_key="k",
    )
    probability, usage = model.decide("state", "question?")
    url, kwargs = calls[0]
    assert url == "https://logos/v1/systemone"
    assert kwargs["json"]["questions"]["answer"]["instructions"] == "question?"
    assert probability == 0.92
    assert (usage.num_input_tokens, usage.num_output_tokens) == (93, 1)
