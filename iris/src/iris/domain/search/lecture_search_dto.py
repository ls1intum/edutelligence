from typing import List

from pydantic import BaseModel, ConfigDict, Field, field_validator

from iris.domain.pipeline_execution_settings_dto import PipelineExecutionSettingsDTO
from iris.domain.status.stage_dto import StageDTO


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


class LectureSearchResultDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    course: CourseInfo
    lecture: LectureInfo
    lecture_unit: LectureUnitInfo = Field(alias="lectureUnit")
    snippet: str


class GlobalSearchRequestDTO(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=10)
    settings: PipelineExecutionSettingsDTO
    initial_stages: List[StageDTO] = Field(alias="initialStages", default_factory=list)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value


class GlobalSearchResponseDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    answer: str | None
    sources: list[LectureSearchResultDTO]
