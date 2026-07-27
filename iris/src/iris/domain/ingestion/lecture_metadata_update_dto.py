from pydantic import BaseModel, ConfigDict, Field


class LectureUnitMetadataUpdateDTO(BaseModel):
    """Lightweight lecture-unit metadata payload sent by Artemis."""

    model_config = ConfigDict(populate_by_name=True)

    lecture_unit_id: int = Field(alias="lectureUnitId")
    lecture_unit_name: str = Field(default="", alias="lectureUnitName")
    lecture_unit_link: str = Field(default="", alias="lectureUnitLink")
    lecture_id: int = Field(alias="lectureId")
    lecture_name: str = Field(default="", alias="lectureName")
    course_id: int = Field(alias="courseId")
    course_name: str = Field(default="", alias="courseName")
    course_description: str = Field(default="", alias="courseDescription")
    video_link: str = Field(default="", alias="videoLink")
    base_url: str = Field(alias="baseUrl")
