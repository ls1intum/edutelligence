from typing import List

from pydantic import BaseModel, Field


class TranscriptionSegmentDTO(BaseModel):
    start_time: float = Field(default="", alias="startTime")
    end_time: float = Field(default="", alias="endTime")
    text: str = Field(default="", alias="text")
    slide_number: int = Field(default=0, alias="slideNumber")
    lecture_unit_id: int = Field(default=0, alias="lectureUnitId")

class TranscriptionDTO(BaseModel):
    language: str = Field(default="", alias="language")
    segments: List[TranscriptionSegmentDTO] = Field(default=[], alias="segments")
    lecture_id: int = Field(alias="lectureId")

class TranscriptionWebhookDTO(BaseModel):
    transcription: TranscriptionDTO = Field(default="", alias="transcription")
    lecture_id: int = Field(alias="lectureId")
    lecture_name: str = Field(default="", alias="lectureName")
    lecture_unit_link: str = Field(default="", alias="lectureUnitLink")
    course_id: int = Field(alias="courseId")
    course_name: str = Field(default="", alias="courseName")
    course_description: str = Field(default="", alias="courseDescription")