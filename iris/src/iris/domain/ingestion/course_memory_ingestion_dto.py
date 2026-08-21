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
    # The channel the thread lives in, NOT the thread itself. Backlinking only.
    conversation_id: str = Field(alias="conversationId")
    # The thread's root post. Dedup/upsert key: one resolved thread, one entry.
    post_id: str = Field(alias="postId")
    # The answer that most recently updated this entry. Provenance only — it is
    # deliberately not the dedup key and is never matched against thread ids.
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

    @model_validator(mode="after")
    def _require_unambiguous_verified_answer(
        self,
    ) -> "CourseMemoryIngestionExecutionDTO":
        """The thread must carry an unambiguous verified answer.

        The extractor synthesizes its answer from the flagged messages only. With
        nothing flagged it would instead pick a message of its own choosing, and
        the result would still be stored under a tutor-verified provenance label
        it did not earn — so reject at the boundary rather than guess.

        Several ``resolves_post`` messages are legitimate (Artemis marks a post
        resolved if *any* answer resolves it) and are merged into one answer. More
        than one ``is_verified_answer`` is not: Artemis derives that flag from a
        single triggering answer, so duplicates mean an upstream bug and leave the
        anchor ambiguous.
        """
        anchors = sum(
            1
            for message in self.thread
            if message.is_verified_answer or message.resolves_post
        )
        if anchors == 0:
            raise ValueError(
                "thread must contain at least one message flagged isVerifiedAnswer "
                "or resolvesPost"
            )
        verified = sum(1 for message in self.thread if message.is_verified_answer)
        if verified > 1:
            raise ValueError(
                "at most one thread message may be flagged isVerifiedAnswer "
                f"(found {verified})"
            )
        return self
