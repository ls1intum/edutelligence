# app/domain/data/metrics/competency_information_dto.py

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

from app.domain.data.competency_dto import CompetencyTaxonomy


class CompetencyInformationDTO(BaseModel):
    id: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    taxonomy: Optional[CompetencyTaxonomy | str] = None
    soft_due_date: Optional[datetime] = Field(None, alias="softDueDate")
    optional: Optional[bool] = None
    mastery_threshold: Optional[int] = Field(None, alias="masteryThreshold")

    class Config:
        populate_by_name = True