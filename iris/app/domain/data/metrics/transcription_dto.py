from typing import List

from pydantic import BaseModel, Field


class TranscriptionSegmentDTO(BaseModel):
    start_time: float = Field(..., alias="startTime")
    end_time: float = Field(..., alias="endTime")
    text: str = Field(..., alias="text")
    slide_number: int = Field(default=0, alias="slideNumber")
    # lecture_unit_id: int = Field(..., alias="lectureUnitId")


class TranscriptionDTO(BaseModel):
    language: str = Field(default="en", alias="language")
    segments: List[TranscriptionSegmentDTO] = Field(..., alias="segments")


class TranscriptionWebhookDTO(BaseModel):
    transcription: TranscriptionDTO = Field(..., alias="transcription")
    lecture_id: int = Field(..., alias="lectureId")
    lecture_name: str = Field(..., alias="lectureName")
    course_id: int = Field(..., alias="courseId")
    course_name: str = Field(..., alias="courseName")
    # course_description: str = Field(..., alias="courseDescription")
