from pydantic import BaseModel
from typing import List


class TranscribeRequestDTO(BaseModel):
    videoUrl: str
    lectureUnitId: int


class TranscriptionSegmentDTO(BaseModel):
    startTime: float
    endTime: float
    text: str
    slideNumber: int


class TranscriptionResponseDTO(BaseModel):
    lectureUnitId: int
    language: str
    segments: List[TranscriptionSegmentDTO]
