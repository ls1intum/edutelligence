from typing import List

from pydantic import BaseModel


class ProgrammingExerciseSolutionEntry(BaseModel):
    file_path: str
    previous_line: int
    line: int
    previous_code: str
    code: str

    def __str__(self):
        return (
            f'ProgrammingExerciseSolutionEntry(file_path="{self.file_path}", previous_line={self.previous_line}, '
            f'line={self.line}, previous_code="{self.previous_code}", code="{self.code}")'
        )


class CodeHint(BaseModel):
    title: str
    description: str
    content: str
    solution_entries: List[ProgrammingExerciseSolutionEntry]

    def __str__(self):
        return (
            f'CodeHint(title="{self.title}", description="{self.description}", content="{self.content}", '
            f"solution_entries={self.solution_entries})"
        )
