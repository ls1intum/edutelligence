from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from iris.domain.data.pyris_lecture_unit_dto import PyrisLectureUnitDTO


class PyrisLectureDTO(BaseModel):
    """DTO for lecture data in chat pipelines.

    Mirrors the Artemis PyrisLectureDTO structure exactly.
    """

    id: int = Field(alias="id")
    title: Optional[str] = Field(alias="title", default=None)
    description: Optional[str] = Field(alias="description", default=None)
    start_date: Optional[datetime] = Field(alias="startDate", default=None)
    end_date: Optional[datetime] = Field(alias="endDate", default=None)
    units: List[PyrisLectureUnitDTO] = Field(alias="units", default=[])
