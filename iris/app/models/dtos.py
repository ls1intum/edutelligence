from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime


class LLMModel(str, Enum):
    GPT35_TURBO = "GPT35_TURBO"


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
    preferred_model: LLMModel = Field(..., alias="preferredModel")
    parameters: dict


class SendMessageResponse(BaseModel):
    class Message(BaseModel):
        sent_at: datetime = Field(
            alias="sentAt", default_factory=datetime.utcnow
        )
        content: Content

    used_model: LLMModel = Field(..., alias="usedModel")
    message: Message
