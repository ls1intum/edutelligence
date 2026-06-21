from typing import List, Optional

from pydantic import Field

from iris.domain.data.course_memory_dto import CourseMemorySource
from iris.domain.data.thread_message_dto import ThreadMessageDTO
from iris.domain.pipeline_execution_dto import PipelineExecutionDTO


class CourseMemoryIngestionExecutionDTO(PipelineExecutionDTO):
    """Execution DTO for course-memory ingestion (Triggers A and B).

    Carries the full public-channel thread plus provenance. ``source``
    distinguishes the trigger: Trigger A (tutor verification) sends one of
    ``IRIS_AUTO`` / ``TUTOR_WRITTEN`` / ``IRIS_CORRECTED``; Trigger B (thread
    resolved) sends ``THREAD_RESOLVED``.
    """

    course_id: int = Field(alias="courseId")
    conversation_id: str = Field(alias="conversationId")
    message_id: str = Field(alias="messageId")
    thread: List[ThreadMessageDTO] = Field(default_factory=list)
    source: CourseMemorySource
    verified_by: Optional[str] = Field(default=None, alias="verifiedBy")
    verified_at: Optional[str] = Field(default=None, alias="verifiedAt")
    is_public_channel: bool = Field(default=True, alias="isPublicChannel")
    existing_answer: Optional[str] = Field(default=None, alias="existingAnswer")
