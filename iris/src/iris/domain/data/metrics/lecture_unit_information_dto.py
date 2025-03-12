from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class LectureUnitInformationDTO(BaseModel):
    id: Optional[int] = None
    name: Optional[str] = None
    release_date: Optional[datetime] = Field(None, alias="releaseDate")
    type: Optional[str] = None

    class Config:
        populate_by_name = True
