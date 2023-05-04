from pydantic import Field

from . import ExerciseType, Exercise
from athena.models.exercise import DBTextExercise


class TextExercise(Exercise):
    """A text exercise that can be solved by students, enhanced with metadata."""

    type: ExerciseType = Field(ExerciseType.text, const=True)

    @staticmethod
    def get_model_class() -> type:
        return DBTextExercise
