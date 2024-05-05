from pydantic import BaseModel, ConfigDict, Field, Json
from typing import Any


class JsonMessageContentDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    json_content: Json[Any] = Field(alias="jsonContent")
