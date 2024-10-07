from typing import Sequence

from pydantic import BaseModel, Field


class FileProblemStatement(BaseModel):
    file_path: str = Field(description="The full path of the file, as specified in the input prompt")
    problem_statement: str = Field(description="Problem statement relevant for this file")


class SplitProblemStatementByFileOutput(BaseModel):
    """Collection of problem statements split by file"""

    items: Sequence[FileProblemStatement] = Field(description="File problem statements")