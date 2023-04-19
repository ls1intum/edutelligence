from dataclasses import dataclass
from enum import Enum


class ExerciseType(str, Enum):
    """The type of the exercise."""
    text = "text"
    programming = "programming"


@dataclass
class Exercise:
    """An exercise that can be solved by students, enhanced with metadata depending on its type."""
    id: int
    title: str
    type: ExerciseType
    max_points: float
    problem_statement: str
    example_solution: str
    package_name: str
    student_id: int
    meta: dict
