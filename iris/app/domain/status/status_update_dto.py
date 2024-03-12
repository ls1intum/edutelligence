from typing import List

from pydantic import BaseModel

from ...domain.status.stage_dto import StageDTO


class StatusUpdateDTO(BaseModel):
    stages: List[StageDTO]
