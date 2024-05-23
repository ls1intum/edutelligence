from pydantic import BaseModel, Field

from datetime import datetime


class SimpleSubmissionDTO(BaseModel):
    timestamp: datetime = Field(alias="timestamp")
    score: float = Field(alias="score")
