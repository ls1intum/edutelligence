from typing import Optional

from pydantic import BaseModel

from app.domain.status.stage_state_dto import StageStateEnum


class StageDTO(BaseModel):
    name: Optional[str] = None
    weight: int
    state: StageStateEnum
    message: Optional[str] = None
