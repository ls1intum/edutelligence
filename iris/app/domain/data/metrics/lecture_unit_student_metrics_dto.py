# app/domain/data/metrics/lecture_unit_student_metrics_dto.py

from pydantic import BaseModel, Field
from typing import Dict, Set

from app.domain.data.metrics.lecture_unit_information_dto import LectureUnitInformationDTO


class LectureUnitStudentMetricsDTO(BaseModel):
    lecture_unit_information: Dict[int, LectureUnitInformationDTO] = Field(alias="lectureUnitInformation")
    completed: Set[int]

    class Config:
        allow_population_by_field_name = True

