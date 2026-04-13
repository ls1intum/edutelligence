from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LectureSearchRequestDTO(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value


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
    start_time: Optional[int] = Field(default=None, alias="startTime")


class LectureSearchResultDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    course: CourseInfo
    lecture: LectureInfo
    lecture_unit: LectureUnitInfo = Field(alias="lectureUnit")
    snippet: str


class LectureSearchAskRequestDTO(BaseModel):
    """Request DTO for the async Ask Iris search endpoint."""

    model_config = ConfigDict(populate_by_name=True)

    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=10)
    artemis_base_url: str = Field(alias="artemisBaseUrl")
    authentication_token: str = Field(alias="authenticationToken")

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value


class LectureSearchAskResponseDTO(BaseModel):
    """Response DTO for the Ask Iris search endpoint."""

    model_config = ConfigDict(populate_by_name=True)

    answer: str
    sources: list[LectureSearchResultDTO]
