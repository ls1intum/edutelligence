from typing import Optional, List

from pydantic import Field, BaseModel

from app.domain import PyrisMessage
from app.domain.data.user_dto import UserDTO


class InteractionSuggestionPipelineExecutionDTO(BaseModel):
    chat_history: List[PyrisMessage] = Field(alias="chatHistory", default=[])
    last_message: Optional[str] = Field(alias="lastMessage", default=None)
