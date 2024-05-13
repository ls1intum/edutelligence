from datetime import datetime
from typing import List
from pydantic import BaseModel, Field

from app.domain.data.lecture_unit_dto import LectureUnitDTO

class PyrisLectureDTO(BaseModel):
    id: int = Field(alias="id")
    title: str = Field(alias="title")
    description: str = Field(alias="description")
    start_date: datetime = Field(alias="startDate")
    end_date: datetime = Field(alias="endDate")
    units: List[LectureUnitDTO] = Field(alias="units")
