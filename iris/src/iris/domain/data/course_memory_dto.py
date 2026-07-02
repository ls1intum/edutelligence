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


class CourseMemoryEntryDTO(BaseModel):
    """A verified Q/A pair stored in the CourseMemory collection.

    ``to_properties`` produces the snake_case dict matching the Weaviate schema
    property names (see :class:`CourseMemorySchema`).
    """

    model_config = ConfigDict(populate_by_name=True)

    question: str
    answer: str
    course_id: int = Field(alias="courseId")
    message_id: str = Field(alias="messageId")
    conversation_id: str = Field(alias="conversationId")
    source: CourseMemorySource
    verified_at: Optional[str] = Field(default=None, alias="verifiedAt")
    verified_by: Optional[str] = Field(default=None, alias="verifiedBy")

    def to_properties(self) -> dict:
        """Return the property dict keyed by the Weaviate schema property names."""
        return {
            CourseMemorySchema.QUESTION.value: self.question,
            CourseMemorySchema.ANSWER.value: self.answer,
            CourseMemorySchema.COURSE_ID.value: self.course_id,
            CourseMemorySchema.MESSAGE_ID.value: self.message_id,
            CourseMemorySchema.CONVERSATION_ID.value: self.conversation_id,
            CourseMemorySchema.SOURCE.value: self.source.value,
            CourseMemorySchema.VERIFIED_AT.value: self.verified_at or "",
            CourseMemorySchema.VERIFIED_BY.value: self.verified_by or "",
        }
