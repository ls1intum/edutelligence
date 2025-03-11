from typing import Dict, Set

from pydantic import BaseModel, Field

from iris.domain.data.metrics.competency_information_dto import (
    CompetencyInformationDTO,
)
from iris.domain.data.metrics.competency_jol_dto import CompetencyJolDTO


class CompetencyStudentMetricsDTO(BaseModel):
    competency_information: Dict[int, CompetencyInformationDTO] = Field(
        {}, alias="competencyInformation"
    )
    exercises: Dict[int, Set[int]] = Field({})
    lecture_units: Dict[int, Set[int]] = Field({}, alias="lectureUnits")
    progress: Dict[int, float] = Field({})
    confidence: Dict[int, float] = Field({})
    jol_values: Dict[int, CompetencyJolDTO] = Field({}, alias="jolValues")

    class Config:
        populate_by_name = True
