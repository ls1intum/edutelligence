from typing import List, Optional

from pydantic import Field

from src.iris.domain import PipelineExecutionDTO, PipelineExecutionSettingsDTO
from src.iris.domain.data.faq_dto import FaqDTO
from src.iris.domain.data.lecture_unit_dto import LectureUnitDTO
from src.iris.domain.status.stage_dto import StageDTO


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
