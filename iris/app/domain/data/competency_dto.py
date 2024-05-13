from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class CompetencyTaxonomy(str, Enum):
    REMEMBER = "REMEMBER"
    UNDERSTAND = "UNDERSTAND"
    APPLY = "APPLY"
    ANALYZE = "ANALYZE"
    EVALUATE = "EVALUATE"
    CREATE = "CREATE"

class CompetencyDTO(BaseModel):
    id: int
    title: str
    description: str
    taxonomy: CompetencyTaxonomy
    soft_due_date: datetime = Field(
        default=None, alias="softDueDate"
    )
    optional: bool