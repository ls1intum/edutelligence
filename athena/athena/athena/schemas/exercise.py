from abc import ABC
from typing import List, Optional

from pydantic import ConfigDict, Field

from .exercise_type import ExerciseType
from .schema import Schema
from .grading_criterion import GradingCriterion


class Exercise(Schema, ABC):
    """An exercise that can be solved by students, enhanced with module-specific metadata."""
    id: int = Field(examples=[1])
    title: str = Field("", description="The title of the exercise.",
                       examples=["Exercise 1"])
    type: ExerciseType = Field(examples=[ExerciseType.text])
    max_points: float = Field(ge=0,
                              description="The maximum number of points that can be achieved.",
                              examples=[1.0])
    bonus_points: float = Field(0.0, ge=0,
                                description="The number of bonus points that can be achieved.",
                                examples=[0.0])
    grading_instructions: Optional[str] = Field(None, description="Markdown text that describes how the exercise is graded.",
                                      examples=["Give 1 point for each correct answer."])
    grading_criteria: Optional[List[GradingCriterion]] = Field(None, description="The structured grading criteria for the exercise as a structured list.")
    problem_statement: Optional[str] = Field(None, description="Markdown text that describes the problem statement.",
                                   examples=["Write a program that prints 'Hello World!'"])

    meta: dict = Field({}, examples=[{"internal_id": "5"}])
    model_config = ConfigDict(from_attributes=True)
