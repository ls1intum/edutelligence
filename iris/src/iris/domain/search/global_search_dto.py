from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator

from iris.domain.pipeline_execution_settings_dto import PipelineExecutionSettingsDTO


class AccessContext(BaseModel):
    """Course IDs grouped by the user's role, resolved by Artemis before the request is sent.

    Pyris treats this as an opaque filter.
    """

    model_config = ConfigDict(populate_by_name=True)

    course_ids: list[int] = Field(default_factory=list, alias="courseIds")
    editor_course_ids: list[int] = Field(default_factory=list, alias="editorCourseIds")
    ta_course_ids: list[int] = Field(default_factory=list, alias="taCourseIds")
    student_course_ids: list[int] = Field(
        default_factory=list, alias="studentCourseIds"
    )
    staff_course_ids: list[int] = Field(default_factory=list, alias="staffCourseIds")
    now: datetime | None = Field(default=None, alias="now")
    unrestricted: bool = Field(default=False, alias="unrestricted")

    def effective_now_dt(self) -> datetime:
        ts = self.now or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)

    def effective_now(self) -> str:
        return self.effective_now_dt().isoformat()

    def is_empty(self) -> bool:
        return len(self.course_ids) == 0


class LectureSearchRequestDTO(BaseModel):
    """Request DTO for the synchronous lecture search endpoint."""

    model_config = ConfigDict(populate_by_name=True)

    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=20)
    course_ids: list[int] | None = Field(default=None, alias="courseIds")
    access_context: AccessContext | None = Field(default=None, alias="accessContext")

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
    """Metadata for a lecture unit returned in search results."""

    model_config = ConfigDict(populate_by_name=True)

    id: int
    name: str
    link: str
    page_number: int = Field(alias="pageNumber")
    source_type: str = Field(alias="sourceType")
    query_params: dict[str, str | int | float] = Field(
        default_factory=dict, alias="queryParams"
    )
    display_meta: str | None = Field(default=None, alias="displayMeta")


class LectureSearchResultDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    course: CourseInfo
    lecture: LectureInfo
    lecture_unit: LectureUnitInfo = Field(alias="lectureUnit")
    snippet: str


class GlobalSearchRequestDTO(BaseModel):
    """Request DTO for the asynchronous global search answer pipeline."""

    model_config = ConfigDict(populate_by_name=True)

    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=10)
    settings: PipelineExecutionSettingsDTO
    access_context: AccessContext | None = Field(default=None, alias="accessContext")

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
