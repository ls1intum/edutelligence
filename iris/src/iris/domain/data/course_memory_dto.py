from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from iris.vector_database.course_memory_schema import CourseMemorySchema


class CourseMemorySource(str, Enum):
    """Origin of a course memory entry."""

    IRIS_AUTO = "IRIS_AUTO"
    TUTOR_WRITTEN = "TUTOR_WRITTEN"
    IRIS_CORRECTED = "IRIS_CORRECTED"
    THREAD_RESOLVED = "THREAD_RESOLVED"


# Sources a tutor signed off on: Trigger A (verification dashboard), or a tutor marking
# an answer as resolving under Trigger B. THREAD_RESOLVED is community-resolved — some
# participant allowed to resolve the thread did so, and no tutor confirmed the content.
# Every reader of the trust tier (the retrieval formatter, the organizational evidence
# guard) keys off this one set, so the two tiers cannot drift apart between modules.
# Stored as the wire/schema string values because that is what a retrieved entry carries.
TUTOR_VERIFIED_SOURCES: frozenset[str] = frozenset(
    source.value
    for source in (
        CourseMemorySource.IRIS_AUTO,
        CourseMemorySource.TUTOR_WRITTEN,
        CourseMemorySource.IRIS_CORRECTED,
    )
)

# Sources whose stored answer is the exact text a tutor signed off on in the dashboard —
# unchanged (IRIS_AUTO) or edited (IRIS_CORRECTED). The payload must carry that text
# verbatim as ``existingAnswer``; letting the extractor paraphrase it would store, and
# later serve as tutor-verified, wording no tutor ever saw.
VERBATIM_ANSWER_SOURCES: frozenset[CourseMemorySource] = frozenset(
    {CourseMemorySource.IRIS_AUTO, CourseMemorySource.IRIS_CORRECTED}
)


class CourseMemoryEntryDTO(BaseModel):
    """A verified Q/A pair stored in the CourseMemory collection.

    ``to_properties`` produces the snake_case dict matching the Weaviate schema
    property names (see :class:`CourseMemorySchema`).
    """

    model_config = ConfigDict(populate_by_name=True)

    question: str
    answer: str
    course_id: int = Field(alias="courseId")
    post_id: str = Field(alias="postId")
    message_id: str = Field(alias="messageId")
    conversation_id: str = Field(alias="conversationId")
    source: CourseMemorySource
    verified_at: Optional[str] = Field(default=None, alias="verifiedAt")
    verified_by: Optional[str] = Field(default=None, alias="verifiedBy")
    # The Artemis operation version this entry was written by; see
    # CourseMemoryIngestionExecutionDTO.version for the ordering it establishes.
    version: int
    # Always False for a live entry. Retractions do not remove the object but turn it
    # into a tombstone with deleted=True, see CourseMemoryDeleter.delete_for_thread.
    deleted: bool = False

    def to_properties(self) -> dict:
        """Return the property dict keyed by the Weaviate schema property names."""
        return {
            CourseMemorySchema.QUESTION.value: self.question,
            CourseMemorySchema.ANSWER.value: self.answer,
            CourseMemorySchema.COURSE_ID.value: self.course_id,
            CourseMemorySchema.POST_ID.value: self.post_id,
            CourseMemorySchema.MESSAGE_ID.value: self.message_id,
            CourseMemorySchema.CONVERSATION_ID.value: self.conversation_id,
            CourseMemorySchema.SOURCE.value: self.source.value,
            CourseMemorySchema.VERIFIED_AT.value: self.verified_at or "",
            CourseMemorySchema.VERIFIED_BY.value: self.verified_by or "",
            CourseMemorySchema.VERSION.value: self.version,
            CourseMemorySchema.DELETED.value: self.deleted,
        }
