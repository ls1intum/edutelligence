import pytest
from pydantic import ValidationError

from iris.domain.data.course_memory_dto import CourseMemorySource
from iris.domain.ingestion.course_memory_ingestion_dto import (
    CourseMemoryIngestionExecutionDTO,
)
from iris.retrieval.course_memory_retrieval_utils import format_course_memories
from iris.vector_database.course_memory_schema import CourseMemorySchema


def _memory(source, message_id="m1", post_id="p1"):
    return {
        CourseMemorySchema.QUESTION.value: "How do I submit?",
        CourseMemorySchema.ANSWER.value: "Use the submit button.",
        CourseMemorySchema.POST_ID.value: post_id,
        CourseMemorySchema.MESSAGE_ID.value: message_id,
        CourseMemorySchema.CONVERSATION_ID.value: "c1",
        CourseMemorySchema.SOURCE.value: source,
    }


def test_empty_returns_notice():
    assert format_course_memories([]) == "No relevant prior answers found."


def test_tutor_sources_are_labeled_verified():
    for source in ("TUTOR_WRITTEN", "IRIS_CORRECTED", "IRIS_AUTO"):
        out = format_course_memories([_memory(source)])
        assert "Verified prior answer" in out
        assert "not tutor-verified" not in out


def test_thread_resolved_is_labeled_unverified():
    out = format_course_memories([_memory("THREAD_RESOLVED")])
    assert "not tutor-verified" in out
    # Must not be misrepresented as a plain "Verified prior answer".
    assert not out.startswith("[Verified prior answer")


def test_backlink_ids_present_in_output():
    out = format_course_memories(
        [_memory("TUTOR_WRITTEN", message_id="answer-42", post_id="post-7")]
    )
    assert "answer-42" in out
    assert "c1" in out
    # The thread backlink must point at the thread root, not the channel: the
    # channel id is what conversation_id actually holds.
    assert "thread: post-7" in out
    assert "channel: c1" in out


def _message(message_id, *, verified=False, resolves=False):
    return {
        "id": message_id,
        "authorRole": "tutor",
        "content": f"content-{message_id}",
        "isVerifiedAnswer": verified,
        "resolvesPost": resolves,
    }


def _thread(*ids):
    """A minimal valid thread: a root post plus one verified answer."""
    return [_message(ids[0])] + [
        _message(message_id, verified=i == 0) for i, message_id in enumerate(ids[1:])
    ]


def test_ingestion_dto_fails_closed_on_public_channel():
    # An omitted isPublicChannel must default to False so private threads are not
    # ingested by a malformed/legacy payload.
    dto = CourseMemoryIngestionExecutionDTO(
        courseId=1,
        conversationId="c1",
        postId="post-1",
        messageId="answer-1",
        thread=_thread("post-1", "answer-1"),
        source=CourseMemorySource.THREAD_RESOLVED,
        settings=None,
    )
    assert dto.is_public_channel is False


def _correction_dto(existing_answer):
    return CourseMemoryIngestionExecutionDTO(
        courseId=1,
        conversationId="c1",
        postId="post-1",
        messageId="answer-1",
        thread=_thread("post-1", "answer-1"),
        source=CourseMemorySource.IRIS_CORRECTED,
        existingAnswer=existing_answer,
        settings=None,
    )


def test_correction_requires_existing_answer():
    # A correction is stored as tutor-verified; without the tutor's actual edit
    # the pipeline would persist LLM output under that label, so reject it.
    for blank in (None, "", "   "):
        with pytest.raises(ValidationError):
            _correction_dto(blank)


def test_correction_accepts_non_blank_existing_answer():
    dto = _correction_dto("The tutor's corrected answer.")
    assert dto.existing_answer == "The tutor's corrected answer."


def _thread_dto(thread, message_id="answer-1"):
    return CourseMemoryIngestionExecutionDTO(
        courseId=1,
        conversationId="c1",
        postId="post-1",
        messageId=message_id,
        thread=thread,
        source=CourseMemorySource.TUTOR_WRITTEN,
        settings=None,
    )


def test_thread_must_flag_a_verified_answer():
    # Nothing flagged means nothing is tagged in the transcript, so the extractor
    # would pick a message of its own choosing and it would be stored as
    # tutor-verified.
    for thread in ([], [_message("post-1"), _message("answer-1")]):
        with pytest.raises(ValidationError, match="at least one message flagged"):
            _thread_dto(thread)


def test_thread_must_not_flag_several_verified_answers():
    # isVerifiedAnswer is derived from a single triggering answer in Artemis, so
    # duplicates mean an upstream bug and leave the anchor ambiguous.
    thread = [
        _message("post-1"),
        _message("answer-1", verified=True),
        _message("answer-2", verified=True),
    ]
    with pytest.raises(ValidationError, match="at most one"):
        _thread_dto(thread)


def test_thread_with_one_verified_answer_is_accepted():
    dto = _thread_dto(_thread("post-1", "answer-1", "answer-2"))
    assert [m.id for m in dto.thread] == ["post-1", "answer-1", "answer-2"]


def test_thread_with_several_resolving_answers_is_accepted():
    # A post is resolved if ANY of its answers resolves it, so several
    # resolvesPost flags are a legitimate state; they are merged into one answer.
    thread = [
        _message("post-1"),
        _message("answer-1", resolves=True),
        _message("answer-2", resolves=True),
        _message("answer-3", resolves=True),
    ]
    dto = _thread_dto(thread)
    assert sum(m.resolves_post for m in dto.thread) == 3


def test_resolving_answer_alone_anchors_the_thread():
    # Trigger B marks an answer resolving without any isVerifiedAnswer flag.
    thread = [_message("post-1"), _message("answer-1", resolves=True)]
    assert _thread_dto(thread).thread[1].resolves_post is True


def test_colliding_post_and_answer_ids_are_accepted():
    # Regression: Artemis draws post and answer ids from separate tables with
    # independent IDENTITY sequences, so a root post and one of its answers
    # routinely share a number. The anchor comes from the flags, never from an id
    # match, so the collision is irrelevant.
    thread = [
        _message("post-7"),
        _message("answer-7", verified=True),
    ]
    dto = _thread_dto(thread, message_id="answer-7")
    assert sum(m.is_verified_answer for m in dto.thread) == 1
    assert dto.thread[1].id == "answer-7"
