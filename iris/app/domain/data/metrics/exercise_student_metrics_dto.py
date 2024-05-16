from typing import Optional, Dict, Set

from pydantic import BaseModel, Field


class ExerciseStudentMetricsDTO(BaseModel):
    """
    A model representing exercise student metrics.

    Attributes:
        average_score: The average score of the students in the exercises.
        score: The score of the student in the exercises.
        average_latest_submission: The average relative time of the latest submissions in the exercises.
        latest_submission: The relative time of the latest submission of the students in the exercises.
    """
    average_score: Optional[Dict[int, float]] = Field(alias="averageScore")
    score: Optional[Dict[int, float]] = Field(alias="score")
    average_latest_submission: Optional[Dict[int, float]] = Field(alias="averageLatestSubmission")
    latest_submission: Optional[Dict[int, float]] = Field(alias="latestSubmission")
    completed: Set[int]

