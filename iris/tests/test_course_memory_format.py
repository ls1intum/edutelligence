from iris.domain.data.course_memory_dto import CourseMemorySource
from iris.domain.ingestion.course_memory_ingestion_dto import (
    CourseMemoryIngestionExecutionDTO,
)
from iris.retrieval.course_memory_retrieval_utils import format_course_memories
from iris.vector_database.course_memory_schema import CourseMemorySchema


def _memory(source, message_id="m1"):
    return {
        CourseMemorySchema.QUESTION.value: "How do I submit?",
        CourseMemorySchema.ANSWER.value: "Use the submit button.",
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
    out = format_course_memories([_memory("TUTOR_WRITTEN", message_id="msg-42")])
    assert "msg-42" in out
    assert "c1" in out


def test_ingestion_dto_fails_closed_on_public_channel():
    # An omitted isPublicChannel must default to False so private threads are not
    # ingested by a malformed/legacy payload.
    dto = CourseMemoryIngestionExecutionDTO(
        courseId=1,
        conversationId="c1",
        messageId="m1",
        source=CourseMemorySource.THREAD_RESOLVED,
        settings=None,
    )
    assert dto.is_public_channel is False
