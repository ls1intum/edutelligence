from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from iris.common.token_usage_dto import TokenUsageDTO
from iris.domain.data.message_content_dto import MessageContentDto
from iris.domain.data.tool_call_dto import ToolCallDTO
from iris.domain.data.tool_message_content_dto import ToolMessageContentDTO


class IrisMessageRole(str, Enum):
    USER = "USER"
    ASSISTANT = "LLM"
    SYSTEM = "SYSTEM"
    TOOL = "TOOL"
    ARTIFACT = "ARTIFACT"


class PyrisMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: Optional[int] = Field(default=None)
    token_usage: TokenUsageDTO = Field(default_factory=TokenUsageDTO)
    sent_at: datetime | None = Field(alias="sentAt", default=None)
    sender: IrisMessageRole
    contents: List[MessageContentDto] = Field(default=[])
    isCloudEnabled: bool = Field(default=False)

    def __str__(self):
        return f"{self.sender.lower()}: {self.contents}"


class PyrisAIMessage(PyrisMessage):
    model_config = ConfigDict(populate_by_name=True)
    sender: IrisMessageRole = IrisMessageRole.ASSISTANT
    tool_calls: Optional[List[ToolCallDTO]] = Field(alias="toolCalls")


class PyrisToolMessage(PyrisMessage):
    model_config = ConfigDict(populate_by_name=True)
    sender: IrisMessageRole = IrisMessageRole.TOOL
    contents: List[ToolMessageContentDTO] = Field(default=[])
