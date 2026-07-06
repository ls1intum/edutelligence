from typing import Optional

from pydantic import Field

from iris.domain import PipelineExecutionDTO, PipelineExecutionSettingsDTO
from iris.domain.data.faq_dto import FaqDTO
from iris.domain.data.lecture_unit_page_dto import LectureUnitPageDTO


class IngestionPipelineExecutionDto(PipelineExecutionDTO):
    lecture_unit: Optional[LectureUnitPageDTO] = Field(None, alias="pyrisLectureUnit")
    lecture_unit_id: int = Field(None, alias="lectureUnitId")
    settings: Optional[PipelineExecutionSettingsDTO]


class FaqIngestionPipelineExecutionDto(PipelineExecutionDTO):
    faq: FaqDTO = Field(..., alias="pyrisFaqWebhookDTO")
    settings: Optional[PipelineExecutionSettingsDTO]
