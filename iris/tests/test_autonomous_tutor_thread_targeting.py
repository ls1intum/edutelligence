"""Iris must answer the newest message of a thread, not the thread's opening post.

Artemis re-runs the autonomous tutor pipeline on every new message and sends the whole
thread each time. Before these tests, the pipeline named the root post as "the student's
post", so a follow-up question was answered with the answer to the opening question.
"""

# The thread helpers under test are pipeline internals; exercising them directly is
# the point of this module.
# pylint: disable=protected-access

from types import SimpleNamespace

import pytest

from iris.common.pyris_message import IrisMessageRole
from iris.domain.data.post_dto import PostDTO
from iris.pipeline.autonomous_tutor_pipeline import AutonomousTutorPipeline
from iris.pipeline.shared.utils import REDACTED_ANSWER_PLACEHOLDER


def _post(*answers: dict, root_role: str = "STUDENT") -> PostDTO:
    return PostDTO.model_validate(
        {
            "id": 1,
            "content": "What is a bridge pattern?",
            "userID": 10,
            "authorRole": root_role,
            "answers": [{"userID": 11, **answer} for answer in answers],
        }
    )


@pytest.fixture(name="pipeline")
def pipeline_fixture() -> AutonomousTutorPipeline:
    # __init__ only loads Jinja templates, no LLM or DB access.
    return AutonomousTutorPipeline()


# ---------------------------------------------------------------------------
# Which message is answered
# ---------------------------------------------------------------------------


def test_target_is_the_newest_reply_not_the_root(pipeline):
    post = _post(
        {"id": 2, "content": "The Bridge Pattern separates...", "authorRole": "IRIS"},
        {
            "id": 3,
            "content": "Then what is a strategy pattern",
            "authorRole": "INSTRUCTOR",
        },
    )

    label, content = pipeline._target_message(post)

    assert content == "Then what is a strategy pattern"
    assert label == "Instructor"


def test_target_is_the_root_when_the_thread_has_no_replies(pipeline):
    label, content = pipeline._target_message(_post())

    assert content == "What is a bridge pattern?"
    assert label == "Student"


def test_target_follows_the_order_artemis_sent(pipeline):
    """The DTO order is authoritative; ids are not used to re-derive chronology."""
    post = _post(
        {"id": 9, "content": "first reply", "authorRole": "STUDENT"},
        {"id": 4, "content": "second reply", "authorRole": "TUTOR"},
    )

    _, content = pipeline._target_message(post)

    assert content == "second reply"


def test_unknown_author_role_gets_a_neutral_label(pipeline):
    post = _post({"id": 2, "content": "a follow-up"})

    label, _ = pipeline._target_message(post)

    assert label == "Course member"


def test_author_role_matching_is_case_insensitive(pipeline):
    """The course-memory ingestion webhook spells the same roles in lower case."""
    post = _post({"id": 2, "content": "a follow-up", "authorRole": "tutor"})

    label, _ = pipeline._target_message(post)

    assert label == "Tutor"


# ---------------------------------------------------------------------------
# Retrieval query
# ---------------------------------------------------------------------------


def test_retrieval_query_is_the_target_message_only(pipeline):
    """The opening question must not leak into the query — that is what made course
    memory re-serve the first answer on every follow-up."""
    post = _post(
        {"id": 2, "content": "The Bridge Pattern separates...", "authorRole": "IRIS"},
        {"id": 3, "content": "Then what is a strategy pattern", "authorRole": "TUTOR"},
    )

    query = pipeline._generate_retrieval_query_text(post)

    assert query == "Then what is a strategy pattern"
    assert "bridge" not in query.lower()


# ---------------------------------------------------------------------------
# Thread as chat history
# ---------------------------------------------------------------------------


def test_thread_becomes_ordered_history_with_roles(pipeline):
    post = _post(
        {"id": 2, "content": "The Bridge Pattern separates...", "authorRole": "IRIS"},
        {
            "id": 3,
            "content": "Then what is a strategy pattern",
            "authorRole": "INSTRUCTOR",
        },
    )
    state = SimpleNamespace(dto=SimpleNamespace(post=post))

    history = pipeline.get_recent_history_from_dto(state, limit=10)

    assert [message.sender for message in history] == [
        IrisMessageRole.USER,
        IrisMessageRole.ASSISTANT,
        IrisMessageRole.USER,
    ]
    texts = [message.contents[0].text_content for message in history]
    assert texts[0] == "[Student] What is a bridge pattern?"
    assert texts[1].startswith("[Iris (you)] ")
    assert texts[2] == "[Instructor] Then what is a strategy pattern"


def test_history_keeps_the_newest_messages_when_truncated(pipeline):
    post = _post(
        *[
            {"id": index, "content": f"reply {index}", "authorRole": "STUDENT"}
            for index in range(2, 7)
        ]
    )
    state = SimpleNamespace(dto=SimpleNamespace(post=post))

    history = pipeline.get_recent_history_from_dto(state, limit=2)

    texts = [message.contents[0].text_content for message in history]
    assert texts == ["[Student] reply 5", "[Student] reply 6"]


def test_redacted_replies_stay_in_the_history_as_placeholders(pipeline):
    post = _post(
        {"id": 2, "content": None, "redacted": True, "authorRole": "STUDENT"},
        {"id": 3, "content": "and what about testing it?", "authorRole": "STUDENT"},
    )
    state = SimpleNamespace(dto=SimpleNamespace(post=post))

    history = pipeline.get_recent_history_from_dto(state, limit=10)

    texts = [message.contents[0].text_content for message in history]
    assert texts[1] == f"[Student] {REDACTED_ANSWER_PLACEHOLDER}"
    assert texts[2] == "[Student] and what about testing it?"


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------


def _render_prompt(pipeline, post) -> str:
    label, content = pipeline._target_message(post)
    return pipeline.system_prompt_template.render(
        {
            "current_date": "2026-08-09",
            "allow_lecture_tool": False,
            "allow_faq_tool": False,
            "allow_course_memory_tool": True,
            "is_programming_exercise": False,
            "is_text_exercise": False,
            "target_author": label,
            "target_message": content,
            "target_is_own_message": label == "Iris (you)",
            "has_thread_context": bool(post.answers),
            "course_name": "Patterns",
        }
    )


def test_prompt_points_at_the_follow_up_not_the_opening_question(pipeline):
    post = _post(
        {"id": 2, "content": "The Bridge Pattern separates...", "authorRole": "IRIS"},
        {
            "id": 3,
            "content": "Then what is a strategy pattern",
            "authorRole": "INSTRUCTOR",
        },
    )

    prompt = _render_prompt(pipeline, post)

    assert "MOST RECENT message" in prompt
    assert "written by [Instructor]" in prompt
    assert "Then what is a strategy pattern" in prompt
    assert "Do NOT answer it again" in prompt


def test_prompt_omits_thread_guidance_for_a_fresh_post(pipeline):
    prompt = _render_prompt(pipeline, _post())

    assert "What is a bridge pattern?" in prompt
    assert "Do NOT answer it again" not in prompt
