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
    evaluations: list[MetricEvaluation] = Field(..., description="The evaluations of the metrics.")

class Evaluation(BaseModel):
    response: Any = Field(..., description="The raw response from the model.")
    parsed_response: MetricEvaluations = Field(..., description="The parsed response from the model.")
    total_tokens: int = Field(..., description="The total number of tokens used.")
    prompt_tokens: int = Field(..., description="The number of tokens used in the prompt.")
    completion_tokens: int = Field(..., description="The number of tokens used in the completion.")
    cost: float = Field(..., description="The total cost of the model invocation.")