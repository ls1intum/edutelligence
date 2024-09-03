from typing import Optional

from pydantic import BaseModel, Field

from datetime import datetime


class SimpleSubmissionDTO(BaseModel):
    timestamp: Optional[datetime] = Field(alias="timestamp", default=None)
    score: Optional[float] = Field(alias="score", default=0)

    class Config:
        require_by_default = False
