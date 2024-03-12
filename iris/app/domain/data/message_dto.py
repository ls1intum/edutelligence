from datetime import datetime
from enum import Enum
from typing import List, Literal

from langchain_core.messages import HumanMessage, AIMessage

from .message_content_dto import MessageContentDTO
from ...domain.iris_message import IrisMessage

from pydantic import BaseModel, Field


class IrisMessageSender(str, Enum):
    USER = "USER"
    LLM = "LLM"


class MessageDTO(BaseModel):
    sent_at: datetime | None = Field(alias="sentAt", default=None)
    sender: Literal[IrisMessageSender.USER, IrisMessageSender.LLM]
    contents: List[MessageContentDTO] = []

    def __str__(self):
        match self.sender:
            case IrisMessageSender.USER:
                sender = "user"
            case IrisMessageSender.LLM:
                sender = "assistant"
            case _:
                raise ValueError(f"Unknown message sender: {self.sender}")
        return f"{sender}: {self.contents[0].text_content}"

    def convert_to_iris_message(self):
        match self.sender:
            case IrisMessageSender.USER:
                sender = "user"
            case IrisMessageSender.LLM:
                sender = "assistant"
            case _:
                raise ValueError(f"Unknown message sender: {self.sender}")

        return IrisMessage(text=self.contents[0].text_content, role=sender)

    def convert_to_langchain_message(self):
        match self.sender:
            case IrisMessageSender.USER:
                return HumanMessage(content=self.contents[0].text_content)
            case IrisMessageSender.LLM:
                return AIMessage(content=self.contents[0].text_content)
            case _:
                raise ValueError(f"Unknown message sender: {self.sender}")
