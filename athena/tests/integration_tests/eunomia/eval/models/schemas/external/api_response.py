from typing import List
from pydantic import BaseModel, Field

from eval.models.schemas.external.feedback import ModelingFeedback

class LLMRequest(BaseModel):
    model: str
    costPerMillionInputToken: float
    costPerMillionOutputToken: float
    numInputTokens: int
    numOutputTokens: int
    numTotalTokens: int

class TotalUsage(BaseModel):
    numInputTokens: int
    numOutputTokens: int
    numTotalTokens: int
    cost: float

class LLMUsage(BaseModel):
    totalUsage: TotalUsage
    llmRequests: List[LLMRequest] = Field(default_factory=list)

class APIResponse(BaseModel):
    module_name: str
    status: int
    data: List[ModelingFeedback] = Field(default_factory=list)
    meta: LLMUsage
