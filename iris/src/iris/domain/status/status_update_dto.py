from typing import List

from pydantic import BaseModel, ConfigDict, Field

from iris.common.token_usage_dto import TokenUsageDTO
from iris.domain.status.run_state_dto import RunStateEnum, StatusErrorDTO


class StatusUpdateDTO(BaseModel):
    # Populate by field name OR alias on input; dump by alias for wire format
    model_config = ConfigDict(populate_by_name=True)

    run_state: RunStateEnum = Field(alias="runState")
    error: StatusErrorDTO | None = None
    tokens: List[TokenUsageDTO] = []
