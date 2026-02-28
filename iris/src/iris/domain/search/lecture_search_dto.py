from pydantic import BaseModel, Field


class LectureSearchRequestDTO(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=20)


class LectureSearchResultDTO(BaseModel):
    lecture_unit_id: int
    lecture_unit_name: str
    lecture_unit_link: str
    lecture_id: int
    lecture_name: str
    course_id: int
    course_name: str
    page_number: int
    snippet: str
