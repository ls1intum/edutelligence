from typing import Optional

from pydantic import BaseModel


class LectureUnitDTO(BaseModel):
    course_id: int
    course_name: str
    course_description: str
    course_language: str
    lecture_id: int
    lecture_name: str
    lecture_unit_id: int
    lecture_unit_name: str
    lecture_unit_link: Optional[str] = ""
    base_url: str
    lecture_unit_summary: Optional[str] = ""
