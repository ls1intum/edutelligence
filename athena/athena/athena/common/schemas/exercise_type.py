from enum import Enum


class ExerciseType(str, Enum):
    """The type of the exercise."""
    text = "text"
    programming = "programming"
