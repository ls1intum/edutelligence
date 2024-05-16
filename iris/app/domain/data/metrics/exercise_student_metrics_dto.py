from typing import Optional, Dict, Set
from pydantic import BaseModel, Field


class ExerciseStudentMetricsDTO(BaseModel):
    average_score: Optional[Dict[int, float]] = Field(None, alias="averageScore")
    score: Optional[Dict[int, float]] = Field(None, alias="score")
    average_latest_submission: Optional[Dict[int, float]] = Field(None, alias="averageLatestSubmission")
    latest_submission: Optional[Dict[int, float]] = Field(None, alias="latestSubmission")
    completed: Optional[Set[int]] = None
