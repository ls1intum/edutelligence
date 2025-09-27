from typing import Optional, Literal
from pydantic import Field

from .exercise_type import ExerciseType
from .exercise import Exercise


class ModelingExercise(Exercise):
    """A modeling exercise that can be solved by students, enhanced with metadata."""

    type: Literal[ExerciseType.modeling] = Field(ExerciseType.modeling)

    example_solution: Optional[str] = Field(None, description="An example solution to the exercise.")
