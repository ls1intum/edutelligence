# app/domain/data/metrics/competency_progress_dto.py

from pydantic import BaseModel, Field


class CompetencyProgressDTO(BaseModel):
    competency_id: int = Field(alias="competencyId")
    progress: float
    confidence: float

    class Config:
        allow_population_by_field_name = True
