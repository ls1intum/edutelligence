# app/domain/data/metrics/competency_student_metrics_dto.py

from pydantic import BaseModel, Field
from typing import Dict, Set, Optional

from app.domain.data.metrics.competency_information_dto import CompetencyInformationDTO


class CompetencyStudentMetricsDTO(BaseModel):
    competency_information: Dict[int, CompetencyInformationDTO] = Field(alias="competencyInformation")
    exercises: Dict[int, Set[int]]
    lecture_units: Dict[int, Set[int]] = Field(alias="lectureUnits")
    progress: Dict[int, float]
    confidence: Dict[int, float]

    class Config:
        allow_population_by_field_name = True
