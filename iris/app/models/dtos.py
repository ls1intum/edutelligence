from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime


class ContentType(str, Enum):
    TEXT = "text"


class Content(BaseModel):
    text_content: str = Field(..., alias="textContent")
    type: ContentType


class SendMessageRequest(BaseModel):
    class Template(BaseModel):
        id: int
        content: str

    template: Template
    preferred_model: str = Field(..., alias="preferredModel")
    parameters: dict


class SendMessageResponse(BaseModel):
    class Message(BaseModel):
        sent_at: datetime = Field(
            alias="sentAt", default_factory=datetime.utcnow
        )
        content: list[Content]

    used_model: str = Field(..., alias="usedModel")
    message: Message


class LLMModelResponse(BaseModel):
    id: str
    name: str
    description: str
