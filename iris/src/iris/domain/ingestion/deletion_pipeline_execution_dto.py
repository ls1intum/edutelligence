from typing import List, Optional

from pydantic import Field

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
    """Removes a thread's course-memory entry when the thread stops being resolved
    in Artemis — the resolving answer was un-marked or deleted, or the thread
    itself was removed (keyed on the thread root ``postId``)."""

    course_id: int = Field(..., alias="courseId")
    post_id: str = Field(..., alias="postId")
    settings: Optional[PipelineExecutionSettingsDTO]
