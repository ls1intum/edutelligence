from typing import List, Optional

from pydantic import Field

from iris.domain import PipelineExecutionDTO, PipelineExecutionSettingsDTO
from iris.domain.data.faq_dto import FaqDTO
from iris.domain.data.lecture_unit_page_dto import LectureUnitPageDTO
from iris.domain.status.stage_dto import StageDTO


class LecturesDeletionExecutionDto(PipelineExecutionDTO):
    lecture_units: List[LectureUnitPageDTO] = Field(..., alias="pyrisLectureUnits")
    settings: Optional[PipelineExecutionSettingsDTO]
    initial_stages: Optional[List[StageDTO]] = Field(
        default=None, alias="initialStages"
    )


class FaqDeletionExecutionDto(PipelineExecutionDTO):
    faq: FaqDTO = Field(..., alias="pyrisFaqWebhookDTO")
    settings: Optional[PipelineExecutionSettingsDTO]
    initial_stages: Optional[List[StageDTO]] = Field(
        default=None, alias="initialStages"
    )


class CourseMemoryDeletionExecutionDto(PipelineExecutionDTO):
    """Removes a single course-memory entry when its source answer is deleted or
    its verification is retracted in Artemis (keyed on the answer ``messageId``)."""

    course_id: int = Field(..., alias="courseId")
    message_id: str = Field(..., alias="messageId")
    settings: Optional[PipelineExecutionSettingsDTO]
    initial_stages: Optional[List[StageDTO]] = Field(
        default=None, alias="initialStages"
    )
