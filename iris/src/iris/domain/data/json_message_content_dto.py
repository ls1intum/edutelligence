from typing import Any, Union

from pydantic import BaseModel, ConfigDict, Field, Json


class JsonMessageContentDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    json_content: Union[Json[Any], dict[str, Any]] = Field(alias="jsonContent")
