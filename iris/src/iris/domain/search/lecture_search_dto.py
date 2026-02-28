from pydantic import BaseModel, Field


class LectureSearchRequestDTO(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=20)


# TODO: Refactor to nested structure to match planned shape:
# { course: { id, name }, lecture: { id, name }, lectureUnit: { id, name, link, pageNumber }, snippet }
class LectureSearchResultDTO(BaseModel):
    lecture_unit_id: int = Field(alias="lectureUnitId")
    lecture_unit_name: str = Field(alias="lectureUnitName")
    lecture_unit_link: str = Field(alias="lectureUnitLink")
    lecture_id: int = Field(alias="lectureId")
    lecture_name: str = Field(alias="lectureName")
    course_id: int = Field(alias="courseId")
    course_name: str = Field(alias="courseName")
    page_number: int = Field(alias="pageNumber")
    snippet: str
