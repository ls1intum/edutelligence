# eval/utils/llm_cost_calculator.py

from typing import Dict, Tuple
from eval.models.schemas.external.api_response import LLMUsage, LLMRequest
from eval.models.schemas.external.llm_costs_config import CaseCostResult, LLMCostsConfig, ModelCostBreakdown, TotalCostUsage, UnknownModelException


class LLMCostCalculator:
    def __init__(self, config: LLMCostsConfig):
        self.config = config

    def compute_case_costs(self, llm_usage: LLMUsage) -> CaseCostResult:
        total_input_tokens = 0
        total_output_tokens = 0
        total_input_cost = 0.0
        total_output_cost = 0.0
        model_costs_map: Dict[str, ModelCostBreakdown] = {}

        for req in llm_usage.llmRequests:
            input_cost, output_cost = self._compute_request_cost(req)

            total_input_tokens += req.numInputTokens
            total_output_tokens += req.numOutputTokens
            total_input_cost += input_cost
            total_output_cost += output_cost

            if req.model not in model_costs_map:
                model_costs_map[req.model] = ModelCostBreakdown(
                    model=req.model,
                    total_calls=0,
                    total_input_tokens=0,
                    total_output_tokens=0,
                    input_cost=0.0,
                    output_cost=0.0
                )

            current = model_costs_map[req.model]
            model_costs_map[req.model] = ModelCostBreakdown(
                model=req.model,
                total_calls=current.total_calls + 1,
                total_input_tokens=current.total_input_tokens + req.numInputTokens,
                total_output_tokens=current.total_output_tokens + req.numOutputTokens,
                input_cost=current.input_cost + input_cost,
                output_cost=current.output_cost + output_cost
            )

        total_usage = TotalCostUsage(
            num_input_tokens=total_input_tokens,
            num_output_tokens=total_output_tokens,
            input_cost=total_input_cost,
            output_cost=total_output_cost
        )

        return CaseCostResult(total_usage=total_usage, model_costs=model_costs_map)

    def _compute_request_cost(self, req: LLMRequest) -> Tuple[float, float]:
        if req.model not in self.config.llm_costs:
            raise UnknownModelException(f"Model '{req.model}' not defined in LLM costs configuration.")

        cost_conf = self.config.llm_costs[req.model]
        input_cost = (req.numInputTokens / 1_000_000) * cost_conf.input_cost_per_million
        output_cost = (req.numOutputTokens / 1_000_000) * cost_conf.output_cost_per_million
        return input_cost, output_cost
