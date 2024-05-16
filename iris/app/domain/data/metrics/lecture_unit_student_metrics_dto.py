from typing import Dict, Set, Optional
from pydantic import BaseModel, Field
from app.domain.data.metrics.lecture_unit_information_dto import LectureUnitInformationDTO


class LectureUnitStudentMetricsDTO(BaseModel):
    lecture_unit_information: Optional[Dict[int, LectureUnitInformationDTO]] = Field(None,
                                                                                     alias="lectureUnitInformation")
    completed: Optional[Set[int]] = None

    class Config:
        allow_population_by_field_name = True
