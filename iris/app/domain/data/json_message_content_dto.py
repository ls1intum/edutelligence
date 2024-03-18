from pydantic import BaseModel, Field, Json
from typing import Any, Optional


class JsonMessageContentDTO(BaseModel):
    json_content: Optional[Json[Any]] = Field(alias="jsonContent", default=None)
