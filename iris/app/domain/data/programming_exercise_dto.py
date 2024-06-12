from typing import Dict, Optional

from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


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
    id: int
    name: str
    programming_language: Optional[str] = Field(
        alias="programmingLanguage", default=None
    )
    template_repository: Dict[str, str] = Field(alias="templateRepository", default={})
    solution_repository: Dict[str, str] = Field(alias="solutionRepository", default={})
    test_repository: Dict[str, str] = Field(alias="testRepository", default={})
    problem_statement: str = Field(alias="problemStatement", default=None)
    start_date: Optional[datetime] = Field(alias="startDate", default=None)
    end_date: Optional[datetime] = Field(alias="endDate", default=None)
