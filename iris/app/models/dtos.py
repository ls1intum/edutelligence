from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime


class LLMStatus(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class ContentType(str, Enum):
    TEXT = "text"


# V1 API only
class Content(BaseModel):
    text_content: str = Field(..., alias="textContent")
    type: ContentType


class SendMessageRequest(BaseModel):
    class Template(BaseModel):
        content: str

    template: Template
    preferred_model: str = Field(..., alias="preferredModel")
    parameters: dict


# V1 API only
class SendMessageResponse(BaseModel):
    class Message(BaseModel):
        sent_at: datetime = Field(
            alias="sentAt", default_factory=datetime.utcnow
        )
        content: list[Content]

    used_model: str = Field(..., alias="usedModel")
    message: Message


class SendMessageRequestV2(BaseModel):
    template: str
    preferred_model: str = Field(..., alias="preferredModel")
    parameters: dict


class SendMessageResponseV2(BaseModel):
    used_model: str = Field(..., alias="usedModel")
    sent_at: datetime = Field(alias="sentAt", default_factory=datetime.utcnow)
    content: dict


class ModelStatus(BaseModel):
    model: str
    status: LLMStatus


class LLMModelResponse(BaseModel):
    id: str
    name: str
    description: str
