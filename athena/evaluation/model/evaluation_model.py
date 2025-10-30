from typing import List

from langchain_core.messages import BaseMessage
from pydantic import BaseModel, Field


class Metric(BaseModel):
    title: str
    summary: str
    description: str


class MetricEvaluation(BaseModel):
    title: str = Field(..., description="The title of the metric.")
    score: int = Field(..., ge=0, le=5, description="The score of the metric.")


class MetricEvaluations(BaseModel):
    evaluations: list[MetricEvaluation] = Field(
        ..., description="The evaluations of the metrics."
    )


class MetricEvaluationRequest(BaseModel):
    prompt: List[BaseMessage] = Field(
        ..., description="The prompt to evaluate the metrics."
    )
    exercise_id: int = Field(..., description="The ID of the exercise.")
    submission_id: int = Field(..., description="The ID of the submission.")
    feedback_type: str = Field(..., description="The type of feedback.")
    metrics: list[Metric] = Field(..., description="The list of metrics to evaluate.")
