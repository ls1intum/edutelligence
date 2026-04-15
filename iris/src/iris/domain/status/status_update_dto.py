from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from iris.common.token_usage_dto import TokenUsageDTO

from ...domain.status.stage_dto import StageDTO


class StatusUpdateDTO(BaseModel):
    # Populate by field name OR alias on input; dump by alias for wire format
    model_config = ConfigDict(populate_by_name=True)

    stages: List[StageDTO]
    tokens: List[TokenUsageDTO] = []
    # Wire key is snake_case `error_code` per spec; the alias makes pydantic
    # accept/emit that key whenever the caller opts into by_alias.
    error_code: Optional[str] = Field(default=None, alias="error_code")
