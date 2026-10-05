from typing import List, Optional

from pydantic import Field, StrictBool, model_validator

from iris.common.artemis_instance import canonical_artemis_base_url
from iris.domain.data.course_memory_dto import (
    VERBATIM_ANSWER_SOURCES,
    CourseMemorySource,
)
from iris.domain.data.thread_message_dto import ThreadMessageDTO
from iris.domain.pipeline_execution_dto import PipelineExecutionDTO
from iris.domain.pipeline_execution_settings_dto import PipelineExecutionSettingsDTO


class CourseMemoryIngestionExecutionDTO(PipelineExecutionDTO):
    """Execution DTO for course-memory ingestion (Triggers A and B).

    Carries the full public-channel thread plus provenance. ``source``
    distinguishes the trigger: Trigger A (tutor verification) sends one of
    ``IRIS_AUTO`` / ``TUTOR_WRITTEN`` / ``IRIS_CORRECTED``; Trigger B (thread
    resolved) sends ``THREAD_RESOLVED``.
    """

    # Narrowed from the optional base field: the ingestion worker reads
    # settings.authentication_token / artemis_base_url before the pipeline exists, so a
    # null would fail in a background thread with no callback left to report it.
    settings: PipelineExecutionSettingsDTO

    course_id: int = Field(alias="courseId")
    # The channel the thread lives in, NOT the thread itself. Backlinking only.
    conversation_id: str = Field(alias="conversationId")
    # The thread's root post. Dedup/upsert key: one resolved thread, one entry.
    post_id: str = Field(alias="postId")
    # The answer that most recently updated this entry. Provenance only — it is
    # deliberately not the dedup key and is never matched against thread ids.
    message_id: str = Field(alias="messageId")
    # Monotonic per-thread operation version, minted by Artemis for every ingestion
    # and every thread-scoped deletion it dispatches. Pyris keeps the highest version
    # it has seen per (courseId, postId) and ignores anything older, so an ingestion
    # accepted before a retraction — or before a newer edit — cannot finish later and
    # overwrite the newer state, whichever order the webhooks arrive in and however
    # long the extraction takes. Required: without it the write cannot be ordered.
    version: int = Field(alias="version", ge=1)
    thread: List[ThreadMessageDTO] = Field(default_factory=list)
    source: CourseMemorySource
    verified_at: Optional[str] = Field(default=None, alias="verifiedAt")
    # Fail closed: an omitted/malformed flag must NOT ingest private content.
    # Strict on purpose — Pydantic's lax mode coerces "yes"/"TRUE"/1 to True, which
    # would turn a malformed payload into permission to ingest a private channel.
    # Rejecting it is the fail-closed reading; the default only covers omission.
    is_public_channel: StrictBool = Field(default=False, alias="isPublicChannel")
    existing_answer: Optional[str] = Field(default=None, alias="existingAnswer")

    @model_validator(mode="after")
    def _require_verbatim_answer_for_dashboard_signoff(
        self,
    ) -> "CourseMemoryIngestionExecutionDTO":
        """A tutor-verified entry must carry the exact text the tutor signed off on.

        ``IRIS_AUTO``, ``IRIS_CORRECTED`` and ``TUTOR_WRITTEN`` mark an entry as
        tutor-verified on the strength of a tutor having read one specific wording.
        Without a non-blank ``existingAnswer`` the pipeline would fall back to LLM
        extraction and still store the result under that label, so retrieval would
        present text no tutor ever saw as tutor-approved. Reject the payload instead.
        """
        if self.source in VERBATIM_ANSWER_SOURCES and not (
            self.existing_answer and self.existing_answer.strip()
        ):
            raise ValueError(
                f"existingAnswer is required when source is {self.source.value}"
            )
        return self

    @model_validator(mode="after")
    def _require_unambiguous_verified_answer(
        self,
    ) -> "CourseMemoryIngestionExecutionDTO":
        """The thread must carry an unambiguous answer source.

        Exactly one message is the anchor (``isVerifiedAnswer``): the answer the entry
        is built from. For a tutor-verified source its text arrives verbatim as
        ``existingAnswer`` and nothing else in the thread may become part of the stored
        answer. For ``THREAD_RESOLVED`` the extractor may additionally merge the other
        ``resolvesPost`` messages, which is why those stay flagged in the payload.
        """
        verified = sum(1 for message in self.thread if message.is_verified_answer)
        if verified != 1:
            raise ValueError(
                "exactly one thread message must be flagged isVerifiedAnswer "
                f"(found {verified})"
            )
        return self

    @model_validator(mode="after")
    def _require_artemis_instance(self) -> "CourseMemoryIngestionExecutionDTO":
        """Every entry is scoped to the Artemis instance that sent it."""
        canonical_artemis_base_url(self.settings.artemis_base_url)
        return self

    @property
    def base_url(self) -> str:
        """Canonical URL of the sending Artemis instance."""
        return canonical_artemis_base_url(self.settings.artemis_base_url)
