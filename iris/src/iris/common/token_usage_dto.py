from pydantic import BaseModel, Field

from iris.common.PipelineEnum import PipelineEnum


class TokenUsageDTO(BaseModel):
    model_info: str = Field(alias="model", default="")
    num_input_tokens: int = Field(alias="numInputTokens", default=0)
    cost_per_input_token: float = Field(alias="costPerMillionInputToken", default=0)
    num_output_tokens: int = Field(alias="numOutputTokens", default=0)
    cost_per_output_token: float = Field(alias="costPerMillionOutputToken", default=0)
    pipeline: PipelineEnum = Field(alias="pipelineId", default=PipelineEnum.NOT_SET)

    def __str__(self):
        return (
            f"{self.model_info}: {self.num_input_tokens} input cost: {self.cost_per_input_token},"
            f" {self.num_output_tokens} output cost: {self.cost_per_output_token}, pipeline: {self.pipeline} "
        )
