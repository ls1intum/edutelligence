from typing import Literal, Any

from pydantic import BaseModel, ConfigDict, Field, Json


class FunctionDTO(BaseModel):
    name: str = Field(..., alias="name")
    arguments: Json[Any] = Field(..., alias="arguments")


class ToolCallDTO(BaseModel):

    model_config = ConfigDict(populate_by_name=True)
    id: str = Field(alias="id")
    type: Literal["function"] = "function"
    function: FunctionDTO = Field(alias="function")
