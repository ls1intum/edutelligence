# app/domain/data/metrics/competency_information_dto.py

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

from app.domain.data.competency_dto import CompetencyTaxonomy


class CompetencyInformationDTO(BaseModel):
    id: int
    title: str
    description: str
    taxonomy: CompetencyTaxonomy  # Assuming CompetencyTaxonomy is an enum or string
    soft_due_date: Optional[datetime] = Field(None, alias="softDueDate")
    optional: bool
    mastery_threshold: int = Field(alias="masteryThreshold")

    class Config:
        allow_population_by_field_name = True
