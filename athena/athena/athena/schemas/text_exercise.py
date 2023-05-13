from pydantic import Field

from .exercise_type import ExerciseType
from .exercise import Exercise


class TextExercise(Exercise):
    """A text exercise that can be solved by students, enhanced with metadata."""

    type: ExerciseType = Field(ExerciseType.text, const=True)
