from typing import Any

from pydantic import BaseModel, ConfigDict, Field, Json


class JsonMessageContentDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    json_content: Json[Any] = Field(alias="jsonContent")
