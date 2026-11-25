import math
from typing import Any

from pydantic import BaseModel, Field, field_validator

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
    # Adapters set this only when the required token counters were reported.
    usage_reported: bool = Field(default=False, exclude=True)
    pipeline: PipelineEnum = Field(alias="pipelineId", default=PipelineEnum.NOT_SET)

    @field_validator("total_cost_usd", mode="before")
    @classmethod
    def validate_usd_cost(cls, cost: Any) -> float | None:
        """Discard bad optional cost data without losing the token record."""
        if cost is None:
            return None
        try:
            if (
                isinstance(cost, (int, float))
                and not isinstance(cost, bool)
                and math.isfinite(cost)
                and cost >= 0
            ):
                return float(cost)
        except OverflowError:
            pass
        logger.warning("Ignoring invalid optional USD cost")
        return None

    def __str__(self):
        return (
            f"{self.model_info}: {self.num_input_tokens} input"
            f" ({self.num_cached_input_tokens} cached, {self.num_cache_write_input_tokens} cache write)"
            f" cost: {self.cost_per_million_input_token},"
            f" {self.num_output_tokens} output cost: {self.cost_per_million_output_token}, pipeline: {self.pipeline} "
        )
