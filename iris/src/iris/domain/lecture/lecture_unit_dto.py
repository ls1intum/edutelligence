from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class LectureUnitDTO(BaseModel):
    """DTO to store all lecture unit information."""

    model_config = ConfigDict(populate_by_name=True)

    course_id: int
    course_name: str
    course_description: str
    course_language: str
    lecture_id: int
    lecture_name: str
    lecture_unit_id: int
    lecture_unit_name: str
    lecture_unit_link: Optional[str] = ""
    video_link: Optional[str] = ""
    base_url: str
    lecture_unit_summary: Optional[str] = ""
    release_date: datetime | None = Field(default=None, alias="releaseDate")
