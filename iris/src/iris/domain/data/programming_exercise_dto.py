from datetime import datetime
from typing import Dict, Optional

from pydantic import BaseModel, Field


class ProgrammingExerciseDTO(BaseModel):
    """Data Transfer Object for representing programming exercises.
    This DTO includes properties such as the programming language, repositories
    for templates, solutions, and tests, as well as the problem statement, start and end dates,
    maximum points, and recent changes (e.g., Git diffs).
    """

    id: int
    title: str = ""
    problem_statement: Optional[str] = Field(alias="problemStatement", default=None)
    start_date: Optional[datetime] = Field(alias="startDate", default=None)
    end_date: Optional[datetime] = Field(alias="endDate", default=None)
    programming_language: Optional[str] = Field(
        alias="programmingLanguage", default=None
    )
    template_repository: Dict[str, str] = Field(alias="templateRepository", default={})
    solution_repository: Dict[str, str] = Field(alias="solutionRepository", default={})
    test_repository: Dict[str, str] = Field(alias="testRepository", default={})
    max_points: Optional[float] = Field(alias="maxPoints", default=None)
    recent_changes: Optional[str] = Field(
        alias="recentChanges",
        default=None,
        description="Git diff of the recent changes",
    )
