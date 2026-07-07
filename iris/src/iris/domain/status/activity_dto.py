from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ActivityKind(str, Enum):
    TOOL = "TOOL"
    COMMAND = "COMMAND"


class ActivityState(str, Enum):
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    FAILED = "FAILED"


class ActivityDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    kind: ActivityKind
    name: str
    state: ActivityState
    detail: Optional[str] = None
    result: Optional[str] = None
    duration_millis: Optional[int] = Field(alias="durationMillis", default=None)
