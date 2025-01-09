from pydantic import BaseModel, Field, PositiveFloat
from typing import Dict
from dataclasses import dataclass

class ModelCostConfig(BaseModel):
    input_cost_per_million: PositiveFloat = Field(..., description="Cost per million input tokens")
    output_cost_per_million: PositiveFloat = Field(..., description="Cost per million output tokens")

class LLMCostsConfig(BaseModel):
    llm_costs: Dict[str, ModelCostConfig] = Field(
        ..., 
        description="A mapping from model name to its cost configuration."
    )

@dataclass(frozen=True)
class ModelCostBreakdown:
    model: str
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    input_cost: float
    output_cost: float

    @property
    def total_cost(self) -> float:
        return self.input_cost + self.output_cost

@dataclass(frozen=True)
class TotalCostUsage:
    num_input_tokens: int
    num_output_tokens: int
    input_cost: float
    output_cost: float

    @property
    def total_tokens(self) -> int:
        return self.num_input_tokens + self.num_output_tokens

    @property
    def total_cost(self) -> float:
        return self.input_cost + self.output_cost

@dataclass(frozen=True)
class CaseCostResult:
    total_usage: TotalCostUsage
    model_costs: Dict[str, ModelCostBreakdown]


class UnknownModelException(Exception):
    """Raised when a model usage is encountered that does not exist in the cost config."""
