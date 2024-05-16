from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime

class LectureUnitInformationDTO(BaseModel):
    id: Optional[int] = None
    name: Optional[str] = None
    release_date: Optional[datetime] = Field(None, alias="releaseDate")
    type: Optional[str] = None

    class Config:
        allow_population_by_field_name = True