from typing import List, Optional

from pydantic import Field

from iris.domain import PipelineExecutionDTO, PipelineExecutionSettingsDTO
from iris.domain.data.faq_dto import FaqDTO
from iris.domain.data.lecture_unit_page_dto import LectureUnitPageDTO
from iris.domain.status.stage_dto import StageDTO


class IngestionPipelineExecutionDto(PipelineExecutionDTO):
    lecture_unit: Optional[LectureUnitPageDTO] = Field(None, alias="pyrisLectureUnit")
    lecture_unit_id: int = Field(None, alias="lectureUnitId")
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
