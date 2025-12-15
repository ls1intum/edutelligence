from typing import List, Optional

from pydantic import BaseModel, Field


class TranscriptionSegmentDTO(BaseModel):
    start_time: float = Field(..., alias="startTime")
    end_time: float = Field(..., alias="endTime")
    text: str = Field(..., alias="text")
    slide_number: int = Field(default=0, alias="slideNumber")


class TranscriptionDTO(BaseModel):
    language: str = Field(default="en", alias="language")
    segments: Optional[List[TranscriptionSegmentDTO]] = Field(
        default=None, alias="segments"
    )


class TranscriptionWebhookDTO(BaseModel):
    transcription: TranscriptionDTO = Field(..., alias="transcription")
    lecture_id: int = Field(..., alias="lectureId")
    lecture_name: str = Field(..., alias="lectureName")
    course_id: int = Field(..., alias="courseId")
    course_name: str = Field(..., alias="courseName")
    course_description: str = Field("", alias="courseDescription")
    lecture_unit_id: int = Field(..., alias="lectureUnitId")
    lecture_unit_name: str = Field("", alias="lectureUnitName")
    lecture_unit_link: str = Field("", alias="lectureUnitLink")
