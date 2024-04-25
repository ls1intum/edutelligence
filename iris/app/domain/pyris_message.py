from datetime import datetime
from enum import Enum
from typing import List

from pydantic import BaseModel, Field

from app.domain.data.message_content_dto import MessageContentDTO


class IrisMessageRole(str, Enum):
    USER = "USER"
    ASSISTANT = "LLM"
    SYSTEM = "SYSTEM"


class PyrisMessage(BaseModel):
    sent_at: datetime | None = Field(alias="sentAt", default=None)
    sender: IrisMessageRole
    contents: List[MessageContentDTO] = []

    def __str__(self):
        return f"{self.sender.lower()}: {self.contents}"
