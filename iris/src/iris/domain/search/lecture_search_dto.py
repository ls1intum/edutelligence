from pydantic import BaseModel


class LectureSearchRequestDTO(BaseModel):
    query: str
    limit: int = 10


class LectureSearchResultDTO(BaseModel):
    lecture_unit_id: int
    lecture_unit_name: str
    lecture_unit_link: str
    lecture_id: int
    lecture_name: str
    course_id: int
    course_name: str
    base_url: str
    page_number: int
    snippet: str
