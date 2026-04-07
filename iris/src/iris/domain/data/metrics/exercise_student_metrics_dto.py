from typing import Dict, Set

from pydantic import BaseModel, Field


class ExerciseStudentMetricsDTO(BaseModel):
    average_score: Dict[int, float] = Field({}, alias="averageScore")
    score: Dict[int, float] = Field({})
    average_latest_submission: Dict[int, float] = Field(
        {}, alias="averageLatestSubmission"
    )
    latest_submission: Dict[int, float] = Field({}, alias="latestSubmission")
    completed: Set[int] = Field(default_factory=set)
