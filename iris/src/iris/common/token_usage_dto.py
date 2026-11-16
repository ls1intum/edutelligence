import math
from typing import Any

from pydantic import BaseModel, Field, model_validator

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum

logger = get_logger(__name__)


class TokenUsageDTO(BaseModel):
    """
    Token usage data transfer object

    ``num_input_tokens`` is the full prompt size. The cached and cache-write
    counts are the parts of it the provider read from or wrote to its prompt
    cache; they are billed at their own rates, the rest at the input rate.
    """

    model_info: str = Field(alias="model", default="")
    num_input_tokens: int = Field(alias="numInputTokens", default=0)
    cost_per_million_input_token: float = Field(
        alias="costPerMillionInputToken", default=0
    )
    num_output_tokens: int = Field(alias="numOutputTokens", default=0)
    cost_per_million_output_token: float = Field(
        alias="costPerMillionOutputToken", default=0
    )
    num_cached_input_tokens: int = Field(alias="numCachedInputTokens", default=0)
    cost_per_million_cached_input_token: float = Field(
        alias="costPerMillionCachedInputToken", default=0
    )
    num_cache_write_input_tokens: int = Field(
        alias="numCacheWriteInputTokens", default=0
    )
    cost_per_million_cache_write_input_token: float = Field(
        alias="costPerMillionCacheWriteInputToken", default=0
    )
    total_cost_usd: float | None = Field(alias="totalCostUsd", default=None)
    cost_source: str | None = Field(alias="costSource", default=None)
    usage_reported: bool = Field(default=True, exclude=True)
    pipeline: PipelineEnum = Field(alias="pipelineId", default=PipelineEnum.NOT_SET)

    @model_validator(mode="before")
    @classmethod
    def validate_usd_cost(cls, data: Any) -> Any:
        """Discard bad optional cost data without losing the token record."""
        if not isinstance(data, dict):
            return data
        cost = data.get("totalCostUsd")
        source = data.get("costSource")
        if cost is None and source is None:
            return data
        try:
            valid_number = (
                isinstance(cost, (int, float))
                and not isinstance(cost, bool)
                and math.isfinite(cost)
                and cost >= 0
            )
        except OverflowError:
            valid_number = False
        if not valid_number or source not in ("PROVIDER", "CONFIGURATION"):
            logger.warning("Ignoring invalid optional USD cost or cost source")
            return {**data, "totalCostUsd": None, "costSource": None}
        return data

    def __str__(self):
        return (
            f"{self.model_info}: {self.num_input_tokens} input"
            f" ({self.num_cached_input_tokens} cached, {self.num_cache_write_input_tokens} cache write)"
            f" cost: {self.cost_per_million_input_token},"
            f" {self.num_output_tokens} output cost: {self.cost_per_million_output_token}, pipeline: {self.pipeline} "
        )
