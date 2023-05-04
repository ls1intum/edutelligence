from pydantic import Field, AnyUrl

from athena.common.schemas import Exercise as CommonExercise, ExerciseType
from athena.storage.models.exercise import DBTextExercise


class Exercise(CommonExercise):
    """A text exercise that can be solved by students, enhanced with metadata."""

    type: ExerciseType = Field(ExerciseType.text, const=True)

    @staticmethod
    def get_model_class() -> type:
        return DBTextExercise
