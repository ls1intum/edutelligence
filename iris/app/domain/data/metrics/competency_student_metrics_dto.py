from typing import Dict, Set, Optional
from pydantic import BaseModel, Field
from app.domain.data.metrics.competency_information_dto import CompetencyInformationDTO


class CompetencyStudentMetricsDTO(BaseModel):
    competency_information: Optional[Dict[int, CompetencyInformationDTO]] = Field(None, alias="competencyInformation")
    exercises: Optional[Dict[int, Set[int]]] = None
    lecture_units: Optional[Dict[int, Set[int]]] = Field(None, alias="lectureUnits")
    progress: Optional[Dict[int, float]] = None
    confidence: Optional[Dict[int, float]] = None
    jol_values: Optional[Dict[int, int]] = Field(None, alias="jolValues")

    class Config:
        populate_by_name = True
