from typing import List, Optional

from pydantic import Field

from app.domain import PipelineExecutionDTO
from app.domain.data.lecture_unit_dto import LectureUnitDTO


class IngestionPipelineExecutionDto(PipelineExecutionDTO):
    lecture_units: List[LectureUnitDTO] = Field(
        ..., alias="pyrisLectureUnitWebhookDTOS"
    )
    full_ingestion_on: Optional[bool] = Field(alias="fullIngestionOn", default=False)
