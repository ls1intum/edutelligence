from typing import List

from pydantic import Field

from ..domain import PipelineExecutionDTO
from .data.lecture_unit_dto import LectureUnitDTO


class IngestionPipelineExecutionDto(PipelineExecutionDTO):
    updated: str = Field(alias="type", default="UPDATED")
    courseId: int = Field(alias="courseId", default=0)
    lecture_units: List[LectureUnitDTO] = Field(alias="units", default=[])
