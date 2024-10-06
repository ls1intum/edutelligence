from typing import Sequence

from pydantic import BaseModel, Field


class FileProblemStatement(BaseModel):
    file_name: str = Field(description="File name")
    problem_statement: str = Field(description="Problem statement relevant for this file")


class SplitProblemStatementByFileOutput(BaseModel):
    """Collection of problem statements split by file"""

    items: Sequence[FileProblemStatement] = Field(description="File problem statements")