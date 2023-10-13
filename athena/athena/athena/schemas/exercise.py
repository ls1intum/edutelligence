from abc import ABC
from typing import List, Optional

from pydantic import Field

from .exercise_type import ExerciseType
from .schema import Schema
from .grading_criterion import GradingCriterion


class Exercise(Schema, ABC):
    """An exercise that can be solved by students, enhanced with module-specific metadata."""
    id: int = Field(example=1)
    title: str = Field("", description="The title of the exercise.",
                       example="Exercise 1")
    type: ExerciseType = Field(example=ExerciseType.text)
    max_points: float = Field(ge=0,
                              description="The maximum number of points that can be achieved.",
                              example=1.0)
    bonus_points: float = Field(0.0, ge=0,
                                description="The number of bonus points that can be achieved.",
                                example=0.0)
    grading_instructions: Optional[str] = Field(None, description="Markdown text that describes how the exercise is graded.",
                                      example="Give 1 point for each correct answer.")
    grading_criteria: Optional[List[GradingCriterion]] = Field(None, description="The grading criteria for the exercise as a structured list.")
    problem_statement: Optional[str] = Field(None, description="Markdown text that describes the problem statement.",
                                   example="Write a program that prints 'Hello World!'")

    meta: dict = Field({}, example={"internal_id": "5"})

    class Config:
        orm_mode = True
