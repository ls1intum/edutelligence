from datetime import datetime
from enum import Enum
from typing import Dict, Optional

from pydantic import BaseModel, Field


class ProgrammingLanguage(str, Enum):
    JAVA = "JAVA"
    PYTHON = "PYTHON"
    C = "C"
    HASKELL = "HASKELL"
    KOTLIN = "KOTLIN"
    VHDL = "VHDL"
    ASSEMBLER = "ASSEMBLER"
    SWIFT = "SWIFT"
    OCAML = "OCAML"
    EMPTY = "EMPTY"


class ProgrammingExerciseDTO(BaseModel):
    """Data Transfer Object for representing programming exercises.
    This DTO includes properties such as the programming language, repositories
    for templates, solutions, and tests, as well as the problem statement, start and end dates,
    maximum points, and recent changes (e.g., Git diffs).
    """

    id: int
    name: str
    programming_language: Optional[str] = Field(
        alias="programmingLanguage", default=None
    )
    template_repository: Dict[str, str] = Field(alias="templateRepository", default={})
    solution_repository: Dict[str, str] = Field(alias="solutionRepository", default={})
    test_repository: Dict[str, str] = Field(alias="testRepository", default={})
    problem_statement: Optional[str] = Field(alias="problemStatement", default=None)
    start_date: Optional[datetime] = Field(alias="startDate", default=None)
    end_date: Optional[datetime] = Field(alias="endDate", default=None)
    max_points: Optional[float] = Field(alias="maxPoints", default=None)
    recent_changes: Optional[str] = Field(
        alias="recentChanges",
        default=None,
        description="Git diff of the recent changes",
    )
