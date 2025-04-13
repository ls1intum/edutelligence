from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ToolMessageContentDTO(BaseModel):

    model_config = ConfigDict(populate_by_name=True)
    name: Optional[str] = Field(alias="toolName", default="")
    tool_content: str = Field(alias="toolContent")
    tool_call_id: str = Field(alias="toolCallId")
