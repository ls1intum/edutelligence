from typing import List, Optional

from pydantic import Field, model_validator

from iris.domain import PipelineExecutionDTO, PipelineExecutionSettingsDTO
from iris.domain.data.faq_dto import FaqDTO
from iris.domain.data.lecture_unit_page_dto import LectureUnitPageDTO


class LecturesDeletionExecutionDto(PipelineExecutionDTO):
    lecture_units: List[LectureUnitPageDTO] = Field(..., alias="pyrisLectureUnits")
    settings: Optional[PipelineExecutionSettingsDTO]


class FaqDeletionExecutionDto(PipelineExecutionDTO):
    faq: FaqDTO = Field(..., alias="pyrisFaqWebhookDTO")
    settings: Optional[PipelineExecutionSettingsDTO]


class CourseMemoryDeletionExecutionDto(PipelineExecutionDTO):
    """Removes course-memory entries that no longer have a source in Artemis.

    Three scopes, exactly one of which must be given:

    * ``postId`` — a single thread stopped being resolved: its resolving answer was
      un-marked or deleted, or the thread itself was removed.
    * ``conversationId`` — a whole channel is gone or is no longer public. Every entry
      mined from it has to go, because eligibility is only evaluated when an entry is
      written; without this, content that was public at ingestion time would keep being
      served after the channel was restricted.
    * ``wholeCourse`` — the course itself was deleted. Artemis drops all of its
      conversations in one bulk statement, so no channel ids survive to purge
      individually and nothing would ever be left to ask for these entries' removal.
    """

    course_id: int = Field(..., alias="courseId")
    post_id: Optional[str] = Field(default=None, alias="postId")
    conversation_id: Optional[str] = Field(default=None, alias="conversationId")
    whole_course: bool = Field(default=False, alias="wholeCourse")
    # Monotonic per-thread operation version, the same counter the ingestion payload
    # carries (see CourseMemoryIngestionExecutionDTO.version). Required for the thread
    # scope, where the retraction competes with in-flight ingestions of that thread and
    # is written as a versioned tombstone; the channel and course scopes delete by filter
    # and carry none. Artemis sends the maximum value when the thread itself was deleted,
    # since nothing legitimate can ever follow that.
    version: Optional[int] = Field(default=None, alias="version", ge=1)
    # Required, unlike the lecture/FAQ deletion DTOs above: the deletion worker reads
    # settings.authentication_token and settings.artemis_base_url to build its status
    # callback, so a null here would surface as a 500 from a background thread that can
    # no longer report anything. Reject it at request validation instead.
    settings: PipelineExecutionSettingsDTO

    @model_validator(mode="after")
    def _require_exactly_one_scope(self) -> "CourseMemoryDeletionExecutionDto":
        """Exactly one of ``postId`` / ``conversationId`` / ``wholeCourse``.

        None of them would delete nothing while still reporting success, and more than
        one would leave the intended scope ambiguous — a deletion that quietly does the
        wrong amount is worse than a rejected request. ``wholeCourse`` is an explicit
        flag rather than "neither id given" for exactly that reason: a client bug that
        drops an id must not silently escalate into wiping a whole course.
        """
        scopes = [bool(self.post_id), bool(self.conversation_id), self.whole_course]
        if sum(scopes) != 1:
            raise ValueError(
                "exactly one of postId, conversationId or wholeCourse must be provided"
            )
        return self

    @model_validator(mode="after")
    def _require_version_for_thread_scope(self) -> "CourseMemoryDeletionExecutionDto":
        """A thread retraction must be ordered against that thread's ingestions.

        Without a version the tombstone could not tell a stale ingestion from a newer
        re-resolution, and the retraction would either be undone by the former or
        wrongly override the latter. Reject rather than guess a version.
        """
        if self.post_id and self.version is None:
            raise ValueError("version is required when deleting a single thread")
        return self
