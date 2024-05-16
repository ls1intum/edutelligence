# app/domain/data/metrics/competency_progress_dto.py

from typing import Optional
from pydantic import BaseModel, Field


class CompetencyProgressDTO(BaseModel):
    competency_id: Optional[int] = Field(None, alias="competencyId")
    progress: Optional[float] = None

    confidence: Optional[float] = None

    class Config:
        allow_population_by_field_name = True
