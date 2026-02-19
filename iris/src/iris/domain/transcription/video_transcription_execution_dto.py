from typing import List, Optional

from pydantic import Field

from iris.domain import PipelineExecutionDTO, PipelineExecutionSettingsDTO
from iris.domain.status.stage_dto import StageDTO


class VideoTranscriptionPipelineExecutionDto(PipelineExecutionDTO):
    """DTO for video transcription pipeline execution requests from Artemis."""

    video_url: str = Field(..., alias="videoUrl")
    lecture_unit_id: int = Field(..., alias="lectureUnitId")
    lecture_id: int = Field(..., alias="lectureId")
    course_id: int = Field(..., alias="courseId")
    course_name: str = Field(..., alias="courseName")
    lecture_name: str = Field(..., alias="lectureName")
    lecture_unit_name: str = Field(..., alias="lectureUnitName")
    settings: Optional[PipelineExecutionSettingsDTO] = None
    initial_stages: Optional[List[StageDTO]] = Field(
        default=None, alias="initialStages"
    )

    class Config:
        populate_by_name = True
