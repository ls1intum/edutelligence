from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field
from pydantic.v1 import validator


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
    soft_due_date: Optional[datetime] = Field(default=None, alias="softDueDate")
    optional: Optional[bool] = None
    exercise_list: Optional[List[int]] = Field(default=[], alias="exerciseList")


class Competency(BaseModel):
    title: str = Field(
        description="Title of the competency that contains no more than 4 words",
    )
    description: str = Field(
        description="Description of the competency as plain string. DO NOT RETURN A LIST OF STRINGS."
    )
    taxonomy: CompetencyTaxonomy = Field(
        description="Selected taxonomy based on bloom's taxonomy"
    )

    @validator("title")
    def validate_title(cls, field):
        """Validate the subject of the competency."""
        if len(field.split()) > 4:
            raise ValueError("Title must contain no more than 4 words")
        return field

    @validator("taxonomy")
    def validate_selected_taxonomy(cls, field):
        """Validate the selected taxonomy."""
        if field not in CompetencyTaxonomy.__members__:
            raise ValueError(f"Invalid taxonomy: {field}")
        return field
