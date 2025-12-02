from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from iris.domain.data.metrics.transcription_dto import TranscriptionDTO


class LectureUnitPageDTO(BaseModel):
    """DTO to ingest attachments and transcriptions for a lecture unit."""

    model_config = ConfigDict(populate_by_name=True)

    pdf_file_base64: str = Field(default="", alias="pdfFile")
    attachment_version: int = Field(default=0, alias="attachmentVersion")
    transcription: Optional[TranscriptionDTO] = Field(default=None)
    lecture_unit_id: int = Field(alias="lectureUnitId")
    lecture_unit_name: str = Field(default="", alias="lectureUnitName")
    lecture_unit_link: str = Field(default="", alias="lectureUnitLink")
    lecture_id: int = Field(alias="lectureId")
    lecture_name: str = Field(default="", alias="lectureName")
    course_id: int = Field(alias="courseId")
    course_name: str = Field(default="", alias="courseName")
    course_description: str = Field(default="", alias="courseDescription")
    video_link: str = Field(default="", alias="videoLink")
