from datetime import datetime, timezone
from typing import List

from pydantic import BaseModel, ConfigDict, Field, field_validator

from iris.domain.pipeline_execution_settings_dto import PipelineExecutionSettingsDTO
from iris.domain.status.stage_dto import StageDTO


class AccessContext(BaseModel):
    """Course IDs grouped by the user's role, resolved by Artemis before the request is sent.
    Pyris treats this as an opaque filter — it applies the IDs to Weaviate queries without
    knowing the business rules that produced them. All access control logic stays in Artemis.

    - course_ids: all courses the user can access at any role (used for lectures, FAQs for students)
    - editor_course_ids: courses where the user is editor/instructor
    - ta_course_ids: courses where the user is teaching assistant
    - student_course_ids: courses where the user is a student
    - staff_course_ids: editor + TA combined (used for FAQ/exam/channel staff access)
    - now: the request timestamp from Artemis, used for date-based visibility filters
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

    def effective_now(self) -> str:
        """ISO 8601 timestamp for date-based Weaviate filters. Uses Artemis-provided now if available."""
        ts = self.now or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.isoformat()

    def is_empty(self) -> bool:
        return len(self.course_ids) == 0


class LectureSearchRequestDTO(BaseModel):
    """Request DTO for the lecture search endpoint."""

    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=20)
    access_context: AccessContext | None = Field(default=None, alias="accessContext")

    model_config = ConfigDict(populate_by_name=True)

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
    """Request DTO for the async global search answer pipeline endpoint."""

    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=10)
    settings: PipelineExecutionSettingsDTO
    initial_stages: List[StageDTO] = Field(alias="initialStages", default_factory=list)
    access_context: AccessContext | None = Field(default=None, alias="accessContext")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value


class GlobalSearchSourceDTO(BaseModel):
    """Unified source result for the Iris answer pipeline.
    Covers all entity types (lecture slides, exercises, FAQs, exams, channels).
    The lecture search endpoint still uses LectureSearchResultDTO unchanged.
    """

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    source_type: str = Field(alias="sourceType")
    entity_id: int = Field(alias="entityId")
    course: CourseInfo
    title: str
    snippet: str | None = None
    # Exercise sub-type (only for sourceType="exercise"): "programming", "quiz", "modeling", "text", "file-upload"
    exercise_type: str | None = Field(default=None, alias="exerciseType")
    # Lecture-specific (only present for lecture_unit_* source types)
    lecture: LectureInfo | None = None
    lecture_unit: LectureUnitInfo | None = Field(default=None, alias="lectureUnit")
    # Internal relevance score from Weaviate hybrid search — not serialized to JSON
    score: float = Field(default=0.0, exclude=True)

    @staticmethod
    def from_lecture_result(
        result: "LectureSearchResultDTO", score: float = 0.0
    ) -> "GlobalSearchSourceDTO":
        return GlobalSearchSourceDTO(
            sourceType=result.lecture_unit.source_type,
            entityId=result.lecture_unit.id,
            course=result.course,
            title=result.lecture_unit.name,
            snippet=result.snippet,
            lecture=result.lecture,
            lectureUnit=result.lecture_unit,
            score=score,
        )


class GlobalSearchResponseDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    answer: str | None
    sources: list[GlobalSearchSourceDTO]
