from enum import Enum
from typing import Dict, Optional

from pydantic import Field

from iris.domain.data.exercise_dto import ExerciseDTO


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


class ProgrammingExerciseDTO(ExerciseDTO):
    """Data Transfer Object for representing programming exercises.
    This DTO includes properties such as the programming language, repositories
    for templates, solutions, and tests, as well as the problem statement, start and end dates,
    maximum points, and recent changes (e.g., Git diffs).
    """

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
