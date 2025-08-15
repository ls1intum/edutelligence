# pylint: disable=invalid-name
from typing import List

from pydantic import BaseModel, ConfigDict


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
