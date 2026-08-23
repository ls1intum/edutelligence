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

    Two scopes, exactly one of which must be given:

    * ``postId`` — a single thread stopped being resolved: its resolving answer was
      un-marked or deleted, or the thread itself was removed.
    * ``conversationId`` — a whole channel is gone or is no longer public. Every entry
      mined from it has to go, because eligibility is only evaluated when an entry is
      written; without this, content that was public at ingestion time would keep being
      served after the channel was restricted.
    """

    course_id: int = Field(..., alias="courseId")
    post_id: Optional[str] = Field(default=None, alias="postId")
    conversation_id: Optional[str] = Field(default=None, alias="conversationId")
    # Required, unlike the lecture/FAQ deletion DTOs above: the deletion worker reads
    # settings.authentication_token and settings.artemis_base_url to build its status
    # callback, so a null here would surface as a 500 from a background thread that can
    # no longer report anything. Reject it at request validation instead.
    settings: PipelineExecutionSettingsDTO

    @model_validator(mode="after")
    def _require_exactly_one_scope(self) -> "CourseMemoryDeletionExecutionDto":
        """Exactly one of ``postId`` / ``conversationId``.

        Neither would delete nothing while still reporting success, and both would leave
        the intended scope ambiguous — a deletion that quietly does the wrong amount is
        worse than a rejected request.
        """
        if bool(self.post_id) == bool(self.conversation_id):
            raise ValueError("exactly one of postId or conversationId must be provided")
        return self
