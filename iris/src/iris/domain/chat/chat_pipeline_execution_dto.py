from typing import List, Optional

from pydantic import Field

from iris.common.pyris_message import PyrisMessage
from iris.domain.data.user_dto import UserDTO
from iris.domain.pipeline_execution_dto import PipelineExecutionDTO


class ChatPipelineExecutionDTO(PipelineExecutionDTO):
    session_title: str = Field(alias="sessionTitle", default=None)
    chat_history: List[PyrisMessage] = Field(alias="chatHistory", default=[])
    user: Optional[UserDTO]
