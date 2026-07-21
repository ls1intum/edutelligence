from datetime import datetime as RealDateTime
from datetime import timedelta, timezone
from types import SimpleNamespace

import pytest

import iris.pipeline.chat.chat_pipeline as chat_pipeline_module
from iris.pipeline.chat.authoritative_evidence import plan_authoritative_evidence
from iris.pipeline.chat.chat_pipeline import ChatPipeline
from iris.pipeline.chat.iris_chat_mode import IrisChatMode

# pylint: disable=protected-access

FROZEN_NOW = RealDateTime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)


class FrozenDateTime(RealDateTime):
    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return FROZEN_NOW.replace(tzinfo=None)
        return FROZEN_NOW.astimezone(tz)


def _state(
    *,
    query="Which competency should I prioritize based on my progress?",
    due_days=3,
    progress=62.0,
    include_metrics=True,
    language="en",
):
    competency = SimpleNamespace(
        id=301,
        title="Sorting Foundations",
        soft_due_date=FROZEN_NOW + timedelta(days=due_days),
    )
    metrics = None
    if include_metrics:
        competency_metrics = SimpleNamespace(
            progress={301: progress},
            competency_information={301: competency},
        )
        metrics = SimpleNamespace(competency_metrics=competency_metrics)
    return SimpleNamespace(
        authoritative_evidence_plan=plan_authoritative_evidence(
            query, IrisChatMode.COURSE
        ),
        dto=SimpleNamespace(
            metrics=metrics,
            course=SimpleNamespace(competencies=[competency]),
            user=SimpleNamespace(lang_key=language),
            settings=SimpleNamespace(support_level="low"),
        ),
    )


def _pipeline(mode=IrisChatMode.COURSE) -> ChatPipeline:
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline.chat_mode = mode
    return pipeline


@pytest.fixture(autouse=True)
def _freeze_production_datetime(monkeypatch):
    monkeypatch.setattr(chat_pipeline_module, "datetime", FrozenDateTime)


def test_applicable_near_soft_due_appends_grounded_plan_question():
    response = "What does your current progress suggest?"

    result = _pipeline()._enforce_near_soft_due_plan_question(_state(), response)

    assert result.startswith(response)
    assert "Sorting Foundations" in result
    assert "62%" in result
    assert "2026-05-20" in result
    assert "what plan will you follow" in result.casefold()
    assert all(
        sentence.strip().endswith("?")
        for sentence in result.splitlines()
        if sentence.strip()
    )


@pytest.mark.parametrize(
    "query",
    [
        "Which competency should I prioritize?",
        "What should I notice about my dashboard?",
        "How is my performance trending?",
        "What study plan should I follow based on my progress?",
    ],
)
def test_explicit_course_evidence_intents_apply_the_rule(query):
    response = "What does the available evidence suggest?"

    result = _pipeline()._enforce_near_soft_due_plan_question(
        _state(query=query), response
    )

    assert result != response
    assert "what plan will you follow" in result.casefold()


def test_existing_plan_question_is_left_unchanged():
    response = "What plan will you follow before the soft due date?"

    result = _pipeline()._enforce_near_soft_due_plan_question(_state(), response)

    assert result == response


def test_offer_to_create_a_plan_does_not_replace_asking_for_the_learners_plan():
    response = (
        "What would help you more right now: a time-block plan, or a "
        "prioritization strategy?"
    )

    result = _pipeline()._enforce_near_soft_due_plan_question(_state(), response)

    assert result != response
    assert "what plan will you follow" in result.casefold()


@pytest.mark.parametrize(
    "query",
    [
        "Hello Iris!",
        "What is a competency?",
        "How do competencies work?",
    ],
)
def test_unrelated_turn_does_not_expose_near_due_metrics(query):
    response = "Hi! How can I help?"
    state = _state(query=query)

    result = _pipeline()._enforce_near_soft_due_plan_question(state, response)

    assert result == response
    assert "62" not in result


def test_missing_authoritative_metrics_leaves_response_unchanged():
    response = "Which area would you like to plan first?"

    result = _pipeline()._enforce_near_soft_due_plan_question(
        _state(include_metrics=False), response
    )

    assert result == response


@pytest.mark.parametrize("due_days", [0, 4])
def test_soft_due_window_boundaries_are_applicable(due_days):
    response = "What does your current progress suggest?"

    result = _pipeline()._enforce_near_soft_due_plan_question(
        _state(due_days=due_days), response
    )

    assert result != response
    assert "what plan will you follow" in result.casefold()


def test_non_course_mode_never_applies_course_coaching_rule():
    response = "What does your current progress suggest?"

    result = _pipeline(IrisChatMode.LECTURE)._enforce_near_soft_due_plan_question(
        _state(), response
    )

    assert result == response


@pytest.mark.parametrize(
    ("due_days", "progress"),
    [
        (-1, 62.0),
        (5, 62.0),
        (3, 70.0),
        (3, 85.0),
    ],
)
def test_past_far_or_sufficient_progress_does_not_trigger(due_days, progress):
    response = "What does your current progress suggest?"

    result = _pipeline()._enforce_near_soft_due_plan_question(
        _state(due_days=due_days, progress=progress), response
    )

    assert result == response


def test_german_applicable_case_appends_one_grounded_plan_question():
    response = "Was zeigt dir dein aktueller Fortschritt?"

    result = _pipeline()._enforce_near_soft_due_plan_question(
        _state(language="de"), response
    )

    assert result.startswith(response)
    assert "Sorting Foundations" in result
    assert "62%" in result
    assert "2026-05-20" in result
    assert "welchen Plan wirst du" in result
    assert all(
        sentence.strip().endswith("?")
        for sentence in result.splitlines()
        if sentence.strip()
    )
