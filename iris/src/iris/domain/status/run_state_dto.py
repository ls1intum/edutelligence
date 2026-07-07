from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict


class RunStateEnum(str, Enum):
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    FAILED = "FAILED"


class StatusErrorDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message: Optional[str] = None
    code: Optional[str] = None
