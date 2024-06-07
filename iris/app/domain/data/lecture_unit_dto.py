from pydantic import BaseModel, Field


class LectureUnitDTO(BaseModel):
    to_update: bool = Field(alias="toUpdate")
    base_url: str = Field(alias="artemisBaseUrl")
    pdf_file_base64: str = Field(default="", alias="pdfFile")
    lecture_unit_id: int = Field(alias="lectureUnitId")
    lecture_unit_name: str = Field(default="", alias="lectureUnitName")
    lecture_id: int = Field(alias="lectureId")
    lecture_name: str = Field(default="", alias="lectureName")
    course_id: int = Field(alias="courseId")
    course_name: str = Field(default="", alias="courseName")
    course_description: str = Field(default="", alias="courseDescription")
