from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PyrisLectureUnitDTO(BaseModel):
    """DTO for lecture unit data in chat pipelines.

    Mirrors the Artemis PyrisLectureUnitDTO structure exactly.
    Used in PyrisLectureDTO.units for lecture chat pipeline execution.
    """

    lecture_unit_id: int = Field(alias="lectureUnitId")
    course_id: int = Field(alias="courseId")
    lecture_id: int = Field(alias="lectureId")
    release_date: Optional[datetime] = Field(alias="releaseDate", default=None)
    name: Optional[str] = Field(default=None)
    attachment_version: Optional[int] = Field(alias="attachmentVersion", default=None)
