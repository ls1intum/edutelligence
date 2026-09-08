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


class EntityCandidateDTO(BaseModel):
    """A pre-fetched SearchableEntities row, forwarded by Artemis.

    Artemis owns entity visibility (channel membership, exam assignment,
    role-dependent release rules live in its database), so it runs the
    filtered entity search and forwards the surviving candidates. Pyris only
    renders, reranks and gates them — it never queries the entity collection
    itself.
    """

    model_config = ConfigDict(populate_by_name=True)

    entity_type: str = Field(alias="entityType")
    entity_id: int | None = Field(default=None, alias="entityId")
    course_id: int | None = Field(default=None, alias="courseId")
    course_name: str | None = Field(default=None, alias="courseName")
    title: str | None = None
    description: str | None = None
    short_name: str | None = Field(default=None, alias="shortName")
    link: str | None = None
    release_date: datetime | None = Field(default=None, alias="releaseDate")
    start_date: datetime | None = Field(default=None, alias="startDate")
    due_date: datetime | None = Field(default=None, alias="dueDate")
    end_date: datetime | None = Field(default=None, alias="endDate")
    visible_date: datetime | None = Field(default=None, alias="visibleDate")
    exam_visible_date: datetime | None = Field(default=None, alias="examVisibleDate")
    exam_start_date: datetime | None = Field(default=None, alias="examStartDate")
    exam_end_date: datetime | None = Field(default=None, alias="examEndDate")
    max_points: float | None = Field(default=None, alias="maxPoints")
    quiz_duration_seconds: int | None = Field(default=None, alias="quizDurationSeconds")
    programming_language: str | None = Field(default=None, alias="programmingLanguage")
    exercise_type: str | None = Field(default=None, alias="exerciseType")
    unit_type: str | None = Field(default=None, alias="unitType")
    faq_state: str | None = Field(default=None, alias="faqState")
    channel_is_public: bool | None = Field(default=None, alias="channelIsPublic")


class EntitySourceDTO(BaseModel):
    """An entity source in the answer response.

    ``snippet`` carries the rendered entity card and is never empty — the
    renderer always produces at least the head line, and the rerank stage
    relies on that.
    """

    model_config = ConfigDict(populate_by_name=True)

    entity_type: str = Field(alias="entityType")
    entity_id: int | None = Field(default=None, alias="entityId")
    course: CourseInfo | None = None
    title: str = ""
    snippet: str = ""
    link: str | None = None
    # Lets the client render the same per-exercise-type icon as the palette.
    exercise_type: str | None = Field(default=None, alias="exerciseType")
    # Internal: True when retrieval admitted this card from the calibrated
    # band BELOW the rerank floor because nothing cleared it — the "no content
    # answers this, but this material seems related" state. The pipeline
    # phrases that as navigation. Never serialized.
    via_pointer_tier: bool = Field(default=False, exclude=True)
    # Internal: the instance's own calendar anchor (start/release date), used
    # to prefer the current semester instance among title-identical twins of
    # a repeated course. Never serialized.
    reference_date: datetime | None = Field(default=None, exclude=True)


class GlobalSearchRequestDTO(BaseModel):
    """Request DTO for the asynchronous global search answer pipeline."""

    model_config = ConfigDict(populate_by_name=True)

    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=10)
    settings: PipelineExecutionSettingsDTO
    access_context: AccessContext | None = Field(default=None, alias="accessContext")
    entity_candidates: list[EntityCandidateDTO] = Field(
        default_factory=list, alias="entityCandidates"
    )
    # Optional course scope from the search UI's active course filter; the
    # retrieval intersects it with the access context.
    course_ids: list[int] | None = Field(default=None, alias="courseIds")

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
    entity_sources: list[EntitySourceDTO] = Field(
        default_factory=list, alias="entitySources"
    )
