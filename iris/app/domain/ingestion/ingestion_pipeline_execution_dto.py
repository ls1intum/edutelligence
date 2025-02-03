from typing import List, Optional

from pydantic import Field

from app.domain import PipelineExecutionDTO, PipelineExecutionSettingsDTO
from app.domain.data.faq_dto import FaqDTO
from app.domain.data.lecture_unit_dto import LectureUnitDTO
from app.domain.status.stage_dto import StageDTO


class IngestionPipelineExecutionDto(PipelineExecutionDTO):
    lecture_unit: LectureUnitDTO = Field(..., alias="pyrisLectureUnit")
    settings: Optional[PipelineExecutionSettingsDTO]
    initial_stages: Optional[List[StageDTO]] = Field(
        default=None, alias="initialStages"
    )


class FaqIngestionPipelineExecutionDto(PipelineExecutionDTO):
    faq: FaqDTO = Field(..., alias="pyrisFaqWebhookDTO")
    settings: Optional[PipelineExecutionSettingsDTO]
    initial_stages: Optional[List[StageDTO]] = Field(
        default=None, alias="initialStages"
    )
