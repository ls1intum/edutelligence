from typing import List, Optional

from pydantic import Field

from src.iris.common.pyris_message import PyrisMessage
from src.iris.domain import PipelineExecutionDTO
from src.iris.domain.data.user_dto import UserDTO


class ChatPipelineExecutionDTO(PipelineExecutionDTO):
    chat_history: List[PyrisMessage] = Field(alias="chatHistory", default=[])
    user: Optional[UserDTO]
