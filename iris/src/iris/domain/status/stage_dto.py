from typing import Optional

from pydantic import BaseModel, Field

from iris.domain.status.stage_state_dto import StageStateEnum


class StageDTO(BaseModel):
    name: Optional[str] = None
    weight: int
    state: StageStateEnum
    message: Optional[str] = None
    internal: bool = Field(
        default=False
    )  # An internal stage is not shown in the UI and hidden from the user
