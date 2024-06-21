from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CompetencyTaxonomy(str, Enum):
    REMEMBER = "REMEMBER"
    UNDERSTAND = "UNDERSTAND"
    APPLY = "APPLY"
    ANALYZE = "ANALYZE"
    EVALUATE = "EVALUATE"
    CREATE = "CREATE"


class CompetencyDTO(BaseModel):
    id: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    taxonomy: Optional[CompetencyTaxonomy] = None
    soft_due_date: Optional[datetime] = Field(
        default=None, alias="softDueDate"
    )
    optional: Optional[bool] = None