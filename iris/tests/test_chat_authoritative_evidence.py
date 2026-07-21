# pylint: disable=protected-access

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from iris.domain.status.activity_dto import ActivityState
from iris.pipeline.chat.authoritative_evidence import (
    is_submission_visibility_intent,
    plan_authoritative_evidence,
    select_repository_files,
)
from iris.pipeline.chat.chat_pipeline import ChatPipeline
from iris.pipeline.chat.iris_chat_mode import IrisChatMode
from iris.pipeline.shared.activity_tracker import ActivityTracker
from iris.tools import chat_tool_providers


@pytest.mark.parametrize(
    ("query", "mode", "expected"),
    [
        (
            "Could you compare my recent marks and pace with the cohort?",
            IrisChatMode.COURSE,
            {"exercise_metrics", "competencies"},
        ),
        (
            "Welche Bereiche meines Fortschritts sind im Kurs schwächer?",
            IrisChatMode.COURSE,
            {"exercise_metrics", "competencies"},
        ),
        (
            "Is there an extension if I miss the hand-in deadline?",
            IrisChatMode.COURSE,
            {"faq"},
        ),
        (
            "Darf ich nach der Abgabefrist noch eine Übungsabgabe machen?",
            IrisChatMode.EXERCISE,
            {"faq"},
        ),
        (
            "The test suite still rejects my output; help me diagnose it.",
            IrisChatMode.EXERCISE,
            {"submission", "feedback", "repository"},
        ),
        (
            "Can you inspect the committed version that Artemis can access?",
            IrisChatMode.EXERCISE,
            {"submission", "repository"},
        ),
        (
            "Compare the recurrence-tree argument with the Master Theorem section.",
            IrisChatMode.LECTURE,
            {"lecture"},
        ),
    ],
)
def test_product_intents_plan_authoritative_evidence(query, mode, expected):
    plan = plan_authoritative_evidence(query, mode)

    assert all(getattr(plan, field) for field in expected)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Can you see my uncommitted local changes?", True),
        ("Which submitted version can Iris inspect?", True),
        (
            "I changed i locally but did not commit. Which version can you inspect?",
            True,
        ),
        ("Kannst du meine nicht committeten Änderungen sehen?", True),
        ("Why does my submitted repository fail this test?", False),
        ("Please inspect the loop in my repository.", False),
    ],
)
def test_submission_visibility_intent_is_distinct_from_debugging(query, expected):
    assert is_submission_visibility_intent(query) is expected


@pytest.mark.parametrize(
    ("query", "mode", "mcq_requested"),
    [
        ("Hello Iris!", IrisChatMode.COURSE, False),
        ("Thanks!", IrisChatMode.COURSE, False),
        ("Make two quiz questions about graphs.", IrisChatMode.COURSE, True),
        ("What do my scores mean?", IrisChatMode.LECTURE, False),
        ("What is amortized complexity?", IrisChatMode.EXERCISE, False),
        ("What is a competency?", IrisChatMode.COURSE, False),
        ("How do competencies work?", IrisChatMode.COURSE, False),
        ("Help me plan a revision session.", IrisChatMode.COURSE, False),
        ("My score improved this week!", IrisChatMode.COURSE, False),
        ("I noted the deadline in my calendar.", IrisChatMode.COURSE, False),
        ("I fail to understand queues.", IrisChatMode.EXERCISE, False),
        ("I'm stuck learning recursion.", IrisChatMode.EXERCISE, False),
        ("Print the complete implementation.", IrisChatMode.EXERCISE, False),
    ],
)
def test_social_mcq_lecture_and_unrelated_intents_do_not_plan_private_evidence(
    query, mode, mcq_requested
):
    plan = plan_authoritative_evidence(query, mode, mcq_requested=mcq_requested)

    assert not plan.active


def test_current_lecture_view_does_not_trigger_redundant_retrieval():
    plan = plan_authoritative_evidence(
        "What does the recurrence on this slide tell me?",
        IrisChatMode.LECTURE,
        has_current_view=True,
    )

    assert not plan.lecture


def test_named_external_lecture_section_retrieves_beyond_current_view():
    plan = plan_authoritative_evidence(
        "Compare this recurrence with the Master Theorem section.",
        IrisChatMode.LECTURE,
        has_current_view=True,
    )

    assert plan.lecture


@pytest.mark.parametrize(
    "query",
    [
        "Why does the recurrence on this slide lead to the stated result?",
        "How is this formula derived from the recurrence shown here?",
        "Kannst du erklären, wie das Ergebnis auf dieser Folie hergeleitet wird?",
        "Warum folgt diese Schranke aus der Rekurrenz im aktuellen Video?",
    ],
)
def test_lecture_reasoning_intent_retrieves_beyond_current_view(query):
    plan = plan_authoritative_evidence(
        query,
        IrisChatMode.LECTURE,
        has_current_view=True,
    )

    assert plan.lecture


@pytest.mark.parametrize(
    "query",
    [
        (r"Why does q(m)=4q(m/2)+m become \Theta(m^2) according to this " "slide?"),
        (
            r"Can you explain how \(u_j = 3u_{j-1}\) leads to \(O(3^j)\) "
            "in the current video?"
        ),
        (
            r"Wie wird aus \(v_i = 2v_{i-1}\) die Schreibweise "
            r"\(O(2^i)\) auf dieser Folie hergeleitet?"
        ),
    ],
)
def test_math_notation_reasoning_retrieves_beyond_current_view(query):
    plan = plan_authoritative_evidence(
        query,
        IrisChatMode.LECTURE,
        has_current_view=True,
    )

    assert plan.lecture


@pytest.mark.parametrize(
    "query",
    [
        "What does h(z)=z^3 show on this slide?",
        "Why is 17 + 25 = 42?",
        "How many examples are shown next to the number 12 on this slide?",
    ],
)
def test_descriptive_notation_and_bare_arithmetic_do_not_retrieve(query):
    plan = plan_authoritative_evidence(
        query,
        IrisChatMode.LECTURE,
        has_current_view=True,
    )

    assert not plan.lecture


@pytest.mark.parametrize("mode", [IrisChatMode.COURSE, IrisChatMode.EXERCISE])
def test_math_reasoning_does_not_plan_lecture_evidence_outside_lecture_mode(mode):
    plan = plan_authoritative_evidence(
        r"Why does p(t)=p(t/2)+t lead to O(t)?",
        mode,
        has_current_view=True,
    )

    assert not plan.lecture


def test_math_reasoning_mcq_request_still_skips_lecture_preflight():
    plan = plan_authoritative_evidence(
        r"Explain why s(k)=2s(k/2)+k and make a quiz question.",
        IrisChatMode.LECTURE,
        has_current_view=True,
        mcq_requested=True,
    )

    assert not plan.lecture


@pytest.mark.parametrize(
    "query",
    [
        "What formula is shown on this slide?",
        "Which result is visible in the current video?",
        "Welche Gleichung steht auf dieser Folie?",
    ],
)
def test_view_limited_descriptive_lecture_questions_do_not_retrieve(query):
    plan = plan_authoritative_evidence(
        query,
        IrisChatMode.LECTURE,
        has_current_view=True,
    )

    assert not plan.lecture


@pytest.mark.parametrize(
    ("query", "mcq_requested"),
    [
        ("Why is the cafeteria closed today?", False),
        ("Hello Iris!", False),
        ("Explain the recurrence and make two quiz questions.", True),
    ],
)
def test_unrelated_social_and_mcq_requests_do_not_plan_lecture_retrieval(
    query, mcq_requested
):
    plan = plan_authoritative_evidence(
        query,
        IrisChatMode.LECTURE,
        has_current_view=True,
        mcq_requested=mcq_requested,
    )

    assert not plan.lecture


def test_programming_events_plan_evidence_without_guessing_from_social_text():
    plan = plan_authoritative_evidence(
        "I just uploaded an attempt.",
        IrisChatMode.EXERCISE,
        event="build_failed",
    )

    assert plan.submission
    assert plan.build_logs
    assert plan.feedback
    assert plan.repository


def test_repository_selection_prefers_named_or_submitted_source_files():
    repository = {
        "target/generated/Generated.java": "generated",
        "README.md": "documentation",
        "src/main/java/Queue.java": "class Queue {}",
        "src/test/java/QueueTest.java": "class QueueTest {}",
        "src/main/java/Other.java": "class Other {}",
    }

    named = select_repository_files("Please inspect Queue.java", repository)
    general = select_repository_files("Why does my submitted code fail?", repository)

    assert named[0] == "src/main/java/Queue.java"
    assert general[0].startswith("src/main/")
    assert all("target/" not in path for path in named + general)


def _pipeline(mode=IrisChatMode.COURSE):
    pipeline = object.__new__(ChatPipeline)
    pipeline.chat_mode = mode
    pipeline.event = None
    return pipeline


def _course_state(query, analytics_enabled=True):
    snapshots = []
    tracker = ActivityTracker(
        lambda activities, seq: snapshots.append((activities, seq))
    )
    state = SimpleNamespace(
        query_text=query,
        dto=SimpleNamespace(
            course=SimpleNamespace(
                student_analytics_dashboard_enabled=analytics_enabled
            ),
            programming_exercise_submission=None,
        ),
        activity_tracker=tracker,
    )
    return state, snapshots


def _named_tool(name, output):
    def tool(*_args):
        return output

    tool.__name__ = name
    return tool


def test_preflight_tracks_real_tool_names_and_injects_results(monkeypatch):
    state, _ = _course_state(
        "Please compare my performance and progress with the class."
    )

    def exercise_provider(state):
        del state
        return _named_tool("get_exercise_list", [{"id": 41}, {"id": 42}])

    monkeypatch.setattr(chat_tool_providers, "provide_exercise_list", exercise_provider)

    def metrics_provider(state):
        del state

        def get_student_exercise_metrics(exercise_ids):
            assert exercise_ids == [41, 42]
            return {41: {"score_of_student": 7.0}}

        return get_student_exercise_metrics

    monkeypatch.setattr(
        chat_tool_providers,
        "provide_student_exercise_metrics",
        metrics_provider,
    )

    def competency_provider(state):
        del state
        return _named_tool("get_competency_list", [{"progress": 0.6}])

    monkeypatch.setattr(
        chat_tool_providers, "provide_competency_list", competency_provider
    )

    pipeline = _pipeline()
    pipeline._preflight_authoritative_evidence(state)

    activities, _ = state.activity_tracker.snapshot()
    assert [item.name for item in activities] == [
        "get_exercise_list",
        "get_student_exercise_metrics",
        "get_competency_list",
    ]
    assert all(item.state is ActivityState.FINISHED for item in activities)
    assert state.authoritative_evidence_provider_names == {
        "exercise_provider",
        "metrics_provider",
        "competency_provider",
    }

    prompt = pipeline._append_authoritative_evidence(
        "BASE", state.authoritative_evidence
    )
    serialized = prompt.split("<authoritative_evidence>", 1)[1].split(
        "</authoritative_evidence>", 1
    )[0]
    evidence = json.loads(serialized)
    assert "score_of_student" in next(
        item["result"]
        for item in evidence
        if item["tool"] == "get_student_exercise_metrics"
    )
    assert "untrusted data" in prompt


def test_lecture_comparison_preflight_tracks_and_injects_retrieved_evidence(
    monkeypatch,
):
    state, _ = _course_state(
        "Compare the recurrence-tree argument with the Master Theorem section."
    )
    state.lecture_contexts = []

    def lecture_provider(state):
        del state
        return _named_tool(
            "lecture_content_retrieval",
            "Master Theorem evidence: a=2, b=2, case 2.",
        )

    monkeypatch.setattr(
        chat_tool_providers, "provide_lecture_retrieval", lecture_provider
    )

    pipeline = _pipeline(IrisChatMode.LECTURE)
    pipeline._preflight_authoritative_evidence(state)

    activities, _ = state.activity_tracker.snapshot()
    assert [item.name for item in activities] == ["lecture_content_retrieval"]
    assert activities[0].state is ActivityState.FINISHED
    assert "Master Theorem evidence" in state.authoritative_evidence[0]["result"]


def test_failed_preflight_tool_is_visible_but_does_not_fail_chat(monkeypatch):
    state, _ = _course_state("How are my scores trending?")

    def provide_exercise_list(state):
        del state

        def get_exercise_list():
            raise RuntimeError("temporary source failure")

        return get_exercise_list

    monkeypatch.setattr(
        chat_tool_providers, "provide_exercise_list", provide_exercise_list
    )
    pipeline = _pipeline()

    pipeline._preflight_authoritative_evidence(state)

    activities, _ = state.activity_tracker.snapshot()
    assert len(activities) == 1
    assert activities[0].state is ActivityState.FAILED
    assert state.authoritative_evidence == []
    assert state.authoritative_evidence_provider_names == set()


def test_greeting_preflight_does_not_construct_any_evidence_provider(monkeypatch):
    state, _ = _course_state("Hi!")
    forbidden = Mock(side_effect=AssertionError("private provider was constructed"))
    monkeypatch.setattr(chat_tool_providers, "provide_exercise_list", forbidden)
    monkeypatch.setattr(
        chat_tool_providers, "provide_student_exercise_metrics", forbidden
    )
    monkeypatch.setattr(chat_tool_providers, "provide_competency_list", forbidden)

    _pipeline()._preflight_authoritative_evidence(state)

    forbidden.assert_not_called()
    assert state.authoritative_evidence == []


def test_disabled_analytics_blocks_all_performance_evidence(monkeypatch):
    state, _ = _course_state(
        "Could you compare my recent marks and progress with the cohort?",
        analytics_enabled=False,
    )
    forbidden = Mock(side_effect=AssertionError("private provider was constructed"))
    monkeypatch.setattr(chat_tool_providers, "provide_exercise_list", forbidden)
    monkeypatch.setattr(
        chat_tool_providers, "provide_student_exercise_metrics", forbidden
    )
    monkeypatch.setattr(chat_tool_providers, "provide_competency_list", forbidden)

    _pipeline()._preflight_authoritative_evidence(state)

    forbidden.assert_not_called()
    assert state.authoritative_evidence == []


def test_preflighted_providers_are_not_offered_for_a_duplicate_agent_call(
    monkeypatch,
):
    calls = []

    def already_used(state):
        del state
        calls.append("already_used")
        return _named_tool("already_used_tool", "duplicate")

    def still_available(state):
        del state
        calls.append("still_available")
        return _named_tool("still_available_tool", "fresh")

    monkeypatch.setattr(
        chat_tool_providers,
        "CHAT_TOOL_PROVIDERS",
        [already_used, still_available],
    )
    state = SimpleNamespace(
        mcq_parallel=False,
        authoritative_evidence_provider_names={"already_used"},
    )
    pipeline = _pipeline()
    pipeline.mcq_pipeline = Mock()

    tools = pipeline.get_tools(state)

    assert calls == ["still_available"]
    assert [tool.__name__ for tool in tools] == ["still_available_tool"]


def test_file_evidence_is_redacted_before_model_context_injection():
    state = SimpleNamespace(authoritative_evidence=[])

    ChatPipeline._store_authoritative_evidence(
        state,
        "file_lookup",
        "config.py:\n" + "API" + "_KEY=" + "sk-" + "example-value-not-real",
    )

    assert ("sk-" + "example-value-not-real") not in state.authoritative_evidence[0][
        "result"
    ]
    assert "[REDACTED_API_KEY]" in state.authoritative_evidence[0]["result"]
