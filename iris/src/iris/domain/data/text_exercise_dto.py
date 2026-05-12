from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class TextExerciseDTO(BaseModel):
    id: int
    title: str = ""
    problem_statement: Optional[str] = Field(alias="problemStatement", default=None)
    start_date: Optional[datetime] = Field(alias="startDate", default=None)
    end_date: Optional[datetime] = Field(alias="endDate", default=None)
    example_solution: Optional[str] = Field(alias="exampleSolution", default=None)
