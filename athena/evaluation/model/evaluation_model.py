from dataclasses import dataclass
from typing import Any, Dict

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
