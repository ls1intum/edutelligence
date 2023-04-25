from enum import Enum

from pydantic import BaseModel, Field


class ExerciseType(str, Enum):
    """The type of the exercise."""
    text = "text"
    programming = "programming"


class Exercise(BaseModel):
    """An exercise that can be solved by students, enhanced with metadata depending on its type."""
    id: int = Field(example=1)
    title: str = Field(example="Exercise 1")
    type: ExerciseType = Field(example=ExerciseType.text)
    max_points: float = Field(example=1.0)
    problem_statement: str = Field(example="Write a program that prints 'Hello World!'")
    example_solution: str = Field(example="print('Hello World!')")
    student_id: int = Field(example=1)
    meta: dict = Field(example={"language": "python"})

    class Config:
        orm_mode = True
