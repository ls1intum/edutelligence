from typing import List, Optional

from pydantic import Field

from iris.common.pyris_message import PyrisMessage
from iris.domain.pipeline_execution_dto import PipelineExecutionDTO
from iris.domain.data.user_dto import UserDTO


class ChatPipelineExecutionDTO(PipelineExecutionDTO):
    chat_history: List[PyrisMessage] = Field(alias="chatHistory", default=[])
    user: Optional[UserDTO]
