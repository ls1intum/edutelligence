from typing import Optional

from pydantic import BaseModel


class LectureUnitDTO(BaseModel):
    course_id: int
    course_name: str
    course_description: str
    course_language: str
    lecture_id: int
    lecture_name: str
    video_unit_id: Optional[int]
    video_unit_name: Optional[str]
    video_unit_link: Optional[str] = ""
    attachment_unit_id: Optional[int]
    attachment_unit_name: Optional[str]
    attachment_unit_link: Optional[str] = ""
    base_url: str
    lecture_unit_summary: Optional[str] = ""
