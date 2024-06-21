from typing import List

from pydantic import Field

from app.domain import PipelineExecutionDTO
from app.domain.data.lecture_unit_dto import LectureUnitDTO


class IngestionPipelineExecutionDto(PipelineExecutionDTO):
    lecture_units: List[LectureUnitDTO] = Field(
        ..., alias="pyrisLectureUnitWebhookDTOS"
    )
