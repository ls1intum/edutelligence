from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class SlideVisibilityDTO(BaseModel):
    """Visibility state for one PDF slide."""

    model_config = ConfigDict(populate_by_name=True)

    slide_number: int = Field(alias="slideNumber", ge=1)
    hidden_until: AwareDatetime | None = Field(default=None, alias="hiddenUntil")


class LectureUnitVisibilityUpdateDTO(BaseModel):
    """Lightweight lecture-unit visibility payload sent by Artemis."""

    model_config = ConfigDict(populate_by_name=True)

    lecture_unit_id: int = Field(alias="lectureUnitId")
    lecture_id: int = Field(alias="lectureId")
    course_id: int = Field(alias="courseId")
    base_url: str = Field(alias="baseUrl")
    release_date: AwareDatetime | None = Field(default=None, alias="releaseDate")
    slides: list[SlideVisibilityDTO] = Field(default_factory=list)
