from typing import Optional

from pydantic import BaseModel, Field

from datetime import datetime


class SimpleSubmissionDTO(BaseModel):
    timestamp: Optional[datetime] = Field(alias="timestamp")
    score: Optional[float] = Field(alias="score")
