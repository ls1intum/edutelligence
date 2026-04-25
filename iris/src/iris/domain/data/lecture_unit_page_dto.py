from pydantic import BaseModel, ConfigDict, Field, field_validator

from iris.domain.data.metrics.transcription_dto import TranscriptionDTO
from iris.domain.data.video_source_type import VideoSourceType


class LectureUnitPageDTO(BaseModel):
    """DTO for lecture unit ingestion webhooks.

    Mirrors the Artemis PyrisLectureUnitWebhookDTO structure.
    Used for ingestion and deletion pipelines.
    """

    model_config = ConfigDict(populate_by_name=True)

    pdf_file_base64: str = Field(default="", alias="pdfFile")
    attachment_version: int = Field(default=0, alias="attachmentVersion")
    transcription: TranscriptionDTO = Field(default=None)
    lecture_unit_id: int = Field(alias="lectureUnitId")
    lecture_unit_name: str = Field(default="", alias="lectureUnitName")
    lecture_unit_link: str = Field(default="", alias="lectureUnitLink")
    lecture_id: int = Field(alias="lectureId")
    lecture_name: str = Field(default="", alias="lectureName")
    course_id: int = Field(alias="courseId")
    course_name: str = Field(default="", alias="courseName")
    course_description: str = Field(default="", alias="courseDescription")
    video_link: str = Field(default="", alias="videoLink")
    video_source_type: VideoSourceType = Field(
        default=VideoSourceType.TUM_LIVE, alias="videoSourceType"
    )

    @field_validator("video_source_type", mode="before")
    @classmethod
    def _coerce_null_video_source_type(cls, value):
        # Pydantic v2 rejects explicit None on a non-Optional Enum field before
        # defaults apply, so older Artemis deployments that emit
        # ``"videoSourceType": null`` would break unless we coerce here.
        return VideoSourceType.TUM_LIVE if value is None else value
