from pydantic import BaseModel, ConfigDict, Field


class LectureSearchRequestDTO(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=20)


class CourseInfo(BaseModel):
    id: int
    name: str


class LectureInfo(BaseModel):
    id: int
    name: str


class LectureUnitInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    name: str
    link: str
    page_number: int = Field(alias="pageNumber")


class LectureSearchResultDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    course: CourseInfo
    lecture: LectureInfo
    lecture_unit: LectureUnitInfo = Field(alias="lectureUnit")
    snippet: str
