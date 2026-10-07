from pydantic import BaseModel, Field

from iris.common.pipeline_enum import PipelineEnum


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
    pipeline: PipelineEnum = Field(alias="pipelineId", default=PipelineEnum.NOT_SET)

    def __str__(self):
        return (
            f"{self.model_info}: {self.num_input_tokens} input"
            f" ({self.num_cached_input_tokens} cached, {self.num_cache_write_input_tokens} cache write)"
            f" cost: {self.cost_per_million_input_token},"
            f" {self.num_output_tokens} output cost: {self.cost_per_million_output_token}, pipeline: {self.pipeline} "
        )
