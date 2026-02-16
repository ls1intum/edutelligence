from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ExerciseDTO(BaseModel):
    name: str  # TODO: name / title
    id: int
    problem_statement: Optional[str] = Field(alias="problemStatement", default=None)
    start_date: Optional[datetime] = Field(alias="startDate", default=None)
    end_date: Optional[datetime] = Field(alias="endDate", default=None)
