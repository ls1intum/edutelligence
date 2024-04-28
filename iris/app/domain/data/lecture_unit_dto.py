from pydantic import BaseModel, Field


class LectureUnitDTO(BaseModel):
    to_update: bool = Field(alias="toUpdate")
    pdf_file_base64: str = Field(alias="pdfFile")  # base64-encoded PDF content
    lecture_unit_id: int = Field(alias="lectureUnitId")
    lecture_unit_name: str = Field(alias="lectureUnitName")
    lecture_id: int = Field(alias="lectureId")
    lecture_name: str = Field(alias="lectureName")
    course_id: int = Field(alias="courseId")
    course_name: str = Field(alias="courseName")
    course_description: str = Field(alias="courseDescription")
