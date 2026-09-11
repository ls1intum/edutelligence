"""Organizational and exam answers must not auto-publish on the model's say-so.

Iris was asked "What will the exam be about?" in a course with no indexed FAQ and no
stored prior answer, and replied with a confident list of exam topics assembled from
the course's subject matter. Nothing in the confidence machinery caught it: the answer
was fluent, so the logprob strategies scored it high, and the prompt asking for honest
self-calibration is advisory.

The guard is the part that does not depend on the model behaving — an organizational
question with no retrieved support cannot carry an auto-publish score.
"""

# The guard hook is a pipeline internal; exercising it directly is the point here.
# pylint: disable=protected-access

from types import SimpleNamespace

import pytest

from iris.config import settings
from iris.domain.data.post_dto import PostDTO
from iris.pipeline.autonomous_tutor_pipeline import AutonomousTutorPipeline
from iris.pipeline.shared.organizational_guard import (
    classify_organizational_question,
    has_organizational_evidence,
    is_organizational_question,
    tutor_verified_memory_hits,
)
from iris.vector_database.course_memory_schema import CourseMemorySchema


def _memory(source):
    """A course-memory hit as CourseMemoryRetrieval returns it: a property dict."""
    return {
        CourseMemorySchema.SOURCE.value: source,
        CourseMemorySchema.QUESTION.value: "When is the exam?",
        CourseMemorySchema.ANSWER.value: "July 30th.",
    }


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question,category",
    [
        ("What will the exam be about?", "exam"),
        ("What day will the exam take place?", "exam"),
        ("Is the exam open book?", "exam"),
        ("Wann ist die Nachklausur?", "exam"),
        ("Wann ist die Anmeldung zur Prüfung?", "exam"),
        ("Wie ist der Notenschlüssel?", "grading"),
        ("How many ECTS is this course worth?", "grading"),
        ("What is the deadline for exercise 3?", "deadline"),
        ("Was ist die Abgabefrist?", "deadline"),
        ("Is attendance mandatory for the tutorial?", "enrollment"),
        ("When are the lecture timings?", "schedule"),
        ("Which room is the tutorial in?", "schedule"),
    ],
)
def test_organizational_questions_are_detected(question, category):
    assert classify_organizational_question(question) == category


@pytest.mark.parametrize(
    "question",
    [
        "What is a bridge pattern?",
        "How does gradient descent work?",
        "Can you explain CI/CD pipelines?",
        "How do I use the terminal to run the tests?",
        "What is the file extension for a Java source file?",
        # "Überprüfung" is verification, not an exam — the Prüfung stem must not fire
        # on it, or every German validation question would be held for review.
        "Die Überprüfung der Eingabe schlägt bei leeren Strings fehl",
        "Ich verstehe die Vorlesungsfolien zu Kapitel 3 nicht",
    ],
)
def test_subject_matter_questions_are_not_flagged(question):
    assert not is_organizational_question(question)


def test_retake_compounds_still_count_as_organizational():
    # "Nachklausur"/"Nachprüfung" are retakes: as organizational as any other exam
    # question. A blanket prefix exclusion built to suppress "Überprüfung" would
    # silence exactly these.
    for question in ("Wann ist die Nachklausur?", "Gibt es eine Nachprüfung?"):
        assert classify_organizational_question(question) == "exam"


def test_empty_message_is_not_organizational():
    for text in (None, "", "   "):
        assert classify_organizational_question(text) is None


# ---------------------------------------------------------------------------
# What counts as support
# ---------------------------------------------------------------------------


def test_faq_or_tutor_verified_memory_hits_count_as_evidence():
    assert has_organizational_evidence([{"faq": 1}], None)
    for source in ("IRIS_AUTO", "TUTOR_WRITTEN", "IRIS_CORRECTED"):
        assert has_organizational_evidence(None, [_memory(source)])


def test_community_resolved_memory_is_not_evidence():
    # A THREAD_RESOLVED entry is a thread some participant marked resolved; no tutor
    # checked the content. Retrieval already hands it to the agent labelled as
    # unverified. Counting it here would let one student's claim about an exam date
    # lift the cap and auto-publish that same claim to the whole course.
    assert not has_organizational_evidence(None, [_memory("THREAD_RESOLVED")])
    assert not has_organizational_evidence([], [_memory("THREAD_RESOLVED")] * 3)


def test_one_verified_hit_among_community_hits_is_enough():
    hits = [_memory("THREAD_RESOLVED"), _memory("TUTOR_WRITTEN")]
    assert has_organizational_evidence(None, hits)
    assert tutor_verified_memory_hits(hits) == [_memory("TUTOR_WRITTEN")]


def test_memory_hit_without_a_readable_source_is_not_evidence():
    # Fail closed: a hit whose provenance cannot be read is not trusted.
    assert not has_organizational_evidence(None, [{"question": "q", "answer": "a"}])
    assert not has_organizational_evidence(None, [{"source": ""}])
    assert not has_organizational_evidence(None, ["not a dict"])


def test_no_hits_is_no_evidence():
    # An empty list is what the tools store when they ran and found nothing — that is
    # the case the guard exists for, so it must not read as support.
    assert not has_organizational_evidence([], [])
    assert not has_organizational_evidence(None, None)


# ---------------------------------------------------------------------------
# The cap
# ---------------------------------------------------------------------------


@pytest.fixture(name="pipeline")
def pipeline_fixture() -> AutonomousTutorPipeline:
    # __init__ only loads Jinja templates, no LLM or DB access.
    return AutonomousTutorPipeline()


def _state(question: str, *, faqs=None, memories=None):
    post = PostDTO.model_validate(
        {"id": 1, "content": question, "userID": 10, "authorRole": "STUDENT"}
    )
    return SimpleNamespace(
        dto=SimpleNamespace(post=post),
        faq_storage={"faqs": faqs} if faqs is not None else {},
        memory_storage={"memories": memories} if memories is not None else {},
    )


@pytest.fixture(name="guard_cap")
def guard_cap_fixture() -> float:
    return settings.autonomous_tutor.organizational_evidence_guard.confidence_cap


def test_unsupported_exam_answer_is_capped_out_of_auto_publish(pipeline, guard_cap):
    # The regression itself: a fluent, ungrounded exam answer scored high enough for
    # Artemis to publish it to students without anyone reading it first.
    state = _state("What will the exam be about?", faqs=[], memories=[])

    capped = pipeline._cap_unsupported_organizational_confidence(state, 0.93)

    assert capped == guard_cap
    assert capped < 0.85  # Artemis's auto-publish threshold


def test_capped_answer_still_reaches_a_tutor(guard_cap):
    # Capping into the review band, not below it: a tutor sees the reply, corrects it,
    # and that correction is what course memory ingests. Dropping it under 0.70 would
    # discard it silently and the question would come back unanswered next semester.
    assert guard_cap >= 0.70


def test_supported_organizational_answer_is_left_alone(pipeline):
    # The FAQ is where instructors put exactly these answers. When it fired, the reply
    # is grounded and may publish on its own.
    state = _state("What day will the exam take place?", faqs=[{"id": 1}], memories=[])

    assert pipeline._cap_unsupported_organizational_confidence(state, 0.93) == 0.93


def test_verified_prior_answer_also_counts_as_support(pipeline):
    state = _state(
        "What day will the exam take place?",
        faqs=[],
        memories=[_memory("TUTOR_WRITTEN")],
    )

    assert pipeline._cap_unsupported_organizational_confidence(state, 0.93) == 0.93


def test_community_resolved_prior_answer_does_not_lift_the_cap(pipeline, guard_cap):
    # The regression Claudia flagged: a matching community claim about an exam date
    # used to count as evidence, so the model's confident echo of it auto-published
    # as authoritative. It has to go to a tutor like any other ungrounded claim.
    state = _state(
        "What day will the exam take place?",
        faqs=[],
        memories=[_memory("THREAD_RESOLVED")],
    )

    assert pipeline._cap_unsupported_organizational_confidence(state, 0.93) == guard_cap


def test_subject_matter_answer_is_untouched(pipeline):
    state = _state("What is a bridge pattern?", faqs=[], memories=[])

    assert pipeline._cap_unsupported_organizational_confidence(state, 0.93) == 0.93


def test_guard_never_raises_a_low_score(pipeline):
    # A model that was already unsure stays unsure and is discarded by Artemis as
    # before. The guard is a ceiling, not an assignment.
    state = _state("What will the exam be about?", faqs=[], memories=[])

    assert pipeline._cap_unsupported_organizational_confidence(state, 0.12) == 0.12


def test_guard_targets_the_newest_message_not_the_thread_root(pipeline, guard_cap):
    # Artemis re-runs the pipeline on every new message, so a follow-up asking about
    # the exam inside a subject-matter thread must be judged on the follow-up.
    post = PostDTO.model_validate(
        {
            "id": 1,
            "content": "What is a bridge pattern?",
            "userID": 10,
            "authorRole": "STUDENT",
            "answers": [
                {
                    "id": 2,
                    "userID": 11,
                    "authorRole": "STUDENT",
                    "content": "And will that be on the exam?",
                }
            ],
        }
    )
    state = SimpleNamespace(
        dto=SimpleNamespace(post=post), faq_storage={}, memory_storage={}
    )

    assert pipeline._cap_unsupported_organizational_confidence(state, 0.93) == guard_cap


def test_guard_can_be_switched_off(pipeline, monkeypatch):
    guard = settings.autonomous_tutor.organizational_evidence_guard
    monkeypatch.setattr(guard, "enabled", False)
    state = _state("What will the exam be about?", faqs=[], memories=[])

    assert pipeline._cap_unsupported_organizational_confidence(state, 0.93) == 0.93
