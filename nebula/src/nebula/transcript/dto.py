# pylint: disable=invalid-name
from pydantic import BaseModel, ConfigDict
from typing import List


class TranscribeRequestDTO(BaseModel):
    videoUrl: str
    lectureUnitId: int


class TranscriptionSegmentDTO(BaseModel):
    startTime: float
    endTime: float
    text: str
    slideNumber: int

    model_config = ConfigDict(extra="forbid")


class TranscriptionResponseDTO(BaseModel):
    lectureUnitId: int
    language: str
    segments: List[TranscriptionSegmentDTO]

    model_config = ConfigDict(extra="forbid")
