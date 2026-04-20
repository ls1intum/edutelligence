from typing import List

from pydantic import BaseModel, ConfigDict

from iris.common.token_usage_dto import TokenUsageDTO

from ...domain.status.stage_dto import StageDTO


class StatusUpdateDTO(BaseModel):
    # Populate by field name OR alias on input; dump by alias for wire format
    model_config = ConfigDict(populate_by_name=True)

    stages: List[StageDTO]
    tokens: List[TokenUsageDTO] = []
