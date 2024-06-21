from typing import List, Optional

from pydantic import Field

from app.domain import PipelineExecutionDTO, PipelineExecutionSettingsDTO
from app.domain.data.lecture_unit_dto import LectureUnitDTO
from app.domain.status.stage_dto import StageDTO


class IngestionPipelineExecutionDto(PipelineExecutionDTO):
    lecture_units: List[LectureUnitDTO] = Field(
        ..., alias="pyrisLectureUnitWebhookDTOS"
    )
    settings: Optional[PipelineExecutionSettingsDTO]
    initial_stages: Optional[List[StageDTO]] = Field(
        default=None, alias="initialStages"
    )
