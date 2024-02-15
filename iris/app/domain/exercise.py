from pydantic import BaseModel


class ProgrammingExercise(BaseModel):
    title: str
    problem_statement: str

    def __str__(self):
        return f'ProgrammingExercise(title="{self.title}", problem_statement="{self.problem_statement}")'
