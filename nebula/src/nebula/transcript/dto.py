from pydantic import BaseModel
from typing import List


class TranscribeRequestDTO(BaseModel):
    videoUrl: str
    lectureId: int
    lectureUnitId: int


class TranscriptionSegmentDTO(BaseModel):
    startTime: float
    endTime: float
    text: str
    slideNumber: int


class TranscriptionResponseDTO(BaseModel):
    lectureId: int
    lectureUnitId: int
    language: str
    segments: List[TranscriptionSegmentDTO]
