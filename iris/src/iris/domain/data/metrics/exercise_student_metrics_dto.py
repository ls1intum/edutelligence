from typing import Dict, Set

from pydantic import BaseModel, Field


class ExerciseStudentMetricsDTO(BaseModel):
    average_score: Dict[int, float] = Field(default_factory=dict, alias="averageScore")
    score: Dict[int, float] = Field(default_factory=dict)
    average_latest_submission: Dict[int, float] = Field(
        default_factory=dict, alias="averageLatestSubmission"
    )
    latest_submission: Dict[int, float] = Field(
        default_factory=dict, alias="latestSubmission"
    )
    completed: Set[int] = Field(default_factory=set)
