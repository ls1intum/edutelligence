from typing import Optional, List
from pydantic import Field

from .exercise_type import ExerciseType
from .exercise import Exercise
from .structured_grading_criterion import StructuredGradingCriterion

class TextExercise(Exercise):
    """A text exercise that can be solved by students, enhanced with metadata."""

    type: ExerciseType = Field(ExerciseType.text, const=True)

    example_solution: Optional[str] = Field(None, description="An example solution to the exercise.")
    structured_grading_criterions: Optional[List[StructuredGradingCriterion]] = Field(
        description="List of structured grading criterions for this exercise."
    )
