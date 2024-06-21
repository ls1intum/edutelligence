from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class CompetencyJolDTO(BaseModel):
    competency_id: Optional[int] = Field(None, alias="competencyId")
    jol_value: Optional[int] = Field(None, alias="jolValue")
    judgement_time: Optional[datetime] = Field(None, alias="judgementTime")
    competency_progress: Optional[float] = Field(None, alias="competencyProgress")
    competency_confidence: Optional[float] = Field(None, alias="competencyConfidence")

    class Config:
        populate_by_name = True
