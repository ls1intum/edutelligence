from typing import List, Optional

from pydantic import Field, model_validator

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
    # Fail closed: an omitted/malformed flag must NOT ingest private content.
    is_public_channel: bool = Field(default=False, alias="isPublicChannel")
    existing_answer: Optional[str] = Field(default=None, alias="existingAnswer")

    @model_validator(mode="after")
    def _require_existing_answer_for_correction(
        self,
    ) -> "CourseMemoryIngestionExecutionDTO":
        """A correction must carry the tutor's edited answer.

        ``IRIS_CORRECTED`` marks an entry as tutor-verified. Without a non-blank
        ``existingAnswer`` the pipeline would fall back to LLM extraction and
        still store the result under the tutor-verified label, so reject the
        payload instead of persisting model-generated text as tutor-corrected.
        """
        if self.source == CourseMemorySource.IRIS_CORRECTED and not (
            self.existing_answer and self.existing_answer.strip()
        ):
            raise ValueError("existingAnswer is required when source is IRIS_CORRECTED")
        return self
