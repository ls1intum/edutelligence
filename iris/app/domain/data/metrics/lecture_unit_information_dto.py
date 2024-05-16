# app/domain/data/metrics/lecture_unit_information_dto.py

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Type, Optional


class LectureUnitInformationDTO(BaseModel):
    id: int
    name: str
    release_date: Optional[datetime] = Field(None, alias="releaseDate")
    type: Type

    class Config:
        allow_population_by_field_name = True
