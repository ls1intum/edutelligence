from pydantic import BaseModel
from typing import List


class TranscribeRequest(BaseModel):
    videoUrl: str
    lectureId: int
    lectureUnitId: int


class TranscriptionSegment(BaseModel):
    startTime: float
    endTime: float
    text: str
    slideNumber: int


class TranscriptionResponse(BaseModel):
    lectureId: int
    lectureUnitId: int
    language: str
    segments: List[TranscriptionSegment]
