from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class LectureUnitDTO(BaseModel):
    id: int
    lecture_id: int = Field(alias="lectureId")
    release_date: Optional[datetime] = Field(alias="releaseDate", default=None)
    name: Optional[str] = None
    attachment_version: int = Field(alias="attachmentVersion")
