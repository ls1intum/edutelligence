from typing import List, Optional

from pydantic import Field

from app.domain import PipelineExecutionDTO
from app.domain.pyris_message import PyrisMessage
from app.domain.data.user_dto import UserDTO


class ChatPipelineExecutionDTO(PipelineExecutionDTO):
    chat_history: List[PyrisMessage] = Field(alias="chatHistory", default=[])
    user: Optional[UserDTO]
