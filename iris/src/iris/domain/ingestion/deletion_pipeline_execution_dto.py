from typing import List, Optional

from pydantic import Field, model_validator

from iris.common.artemis_instance import canonical_artemis_base_url
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
    """Retracts the Course Memory entry of one thread by writing a versioned tombstone.

    Sent when a thread stops qualifying — its resolving answer was un-marked or deleted,
    its root author opted out, or the thread itself was removed (Artemis then sends the
    maximum version, since nothing legitimate can follow a deleted thread). Channel and
    course scopes no longer exist: Iris only ever cites from channels Artemis lists as
    readable at run time, and the nightly sync removes what a deleted channel or course
    left behind.
    """

    course_id: int = Field(..., alias="courseId")
    post_id: str = Field(..., alias="postId")
    # Monotonic per-thread operation version, the same counter the ingestion payload
    # carries (see CourseMemoryIngestionExecutionDTO.version). The tombstone keeps it,
    # so an older ingestion that finishes later gives up instead of re-inserting the
    # retracted answer.
    version: int = Field(..., alias="version", ge=1)
    # Required, unlike the lecture/FAQ deletion DTOs above: the deletion worker reads
    # settings.authentication_token and settings.artemis_base_url to build its status
    # callback and to scope the tombstone to the sending instance.
    settings: PipelineExecutionSettingsDTO

    @model_validator(mode="after")
    def _require_artemis_instance(self) -> "CourseMemoryDeletionExecutionDto":
        """Every tombstone is scoped to the Artemis instance that sent it."""
        canonical_artemis_base_url(self.settings.artemis_base_url)
        return self

    @property
    def base_url(self) -> str:
        """Canonical URL of the sending Artemis instance."""
        return canonical_artemis_base_url(self.settings.artemis_base_url)
