from pydantic import Field

from . import ExerciseType, Exercise


class TextExercise(Exercise):
    """A text exercise that can be solved by students, enhanced with metadata."""

    type: ExerciseType = Field(ExerciseType.text, const=True)
