from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class LectureUnitDTO(BaseModel):
    id: int
    lecture_id: int = Field(alias="lectureId")
    release_date: Optional[datetime] = Field(alias="releaseDate", default=None)
    unit_name: Optional[str] = Field(alias="unitName", default="")
    lecture_name: Optional[str] = Field(alias="lectureName", default="")
    attachment_version: int = Field(alias="attachmentVersion")
    raw_data: str = Field(alias="rawData")
