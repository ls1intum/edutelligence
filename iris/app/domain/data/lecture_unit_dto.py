from typing import Optional

from pydantic import BaseModel, Field


class LectureUnitDTO(BaseModel):
    to_update: Optional[bool] = Field(alias="toUpdate", default=None)
    pdf_file_base64: Optional[str] = Field(alias="pdfFile", default=None)
    lecture_unit_id: Optional[int] = Field(alias="lectureUnitId", default=None)
    lecture_unit_name: Optional[str] = Field(alias="lectureUnitName", default=None)
    lecture_id: Optional[int] = Field(alias="lectureId", default=None)
    lecture_name: Optional[str] = Field(alias="lectureName", default=None)
    course_id: Optional[int] = Field(alias="courseId", default=None)
    course_name: Optional[str] = Field(alias="courseName", default=None)
    course_description: Optional[str] = Field(alias="courseDescription", default=None)
