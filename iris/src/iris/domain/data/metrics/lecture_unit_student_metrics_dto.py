from typing import Dict, Optional, Set

from pydantic import BaseModel, Field

from iris.domain.data.metrics.lecture_unit_information_dto import (
    LectureUnitInformationDTO,
)


class LectureUnitStudentMetricsDTO(BaseModel):
    lecture_unit_information: Dict[int, LectureUnitInformationDTO] = Field(
        {}, alias="lectureUnitInformation"
    )
    completed: Optional[Set[int]] = None

    class Config:
        populate_by_name = True
