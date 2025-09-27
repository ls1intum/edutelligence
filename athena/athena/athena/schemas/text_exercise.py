from typing import Optional, Literal
from pydantic import Field

from .exercise_type import ExerciseType
from .exercise import Exercise


class TextExercise(Exercise):
    """A text exercise that can be solved by students, enhanced with metadata."""

    type: Literal[ExerciseType.text] = Field(ExerciseType.text)

    example_solution: Optional[str] = Field(None, description="An example solution to the exercise.")
