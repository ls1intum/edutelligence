from typing import List, Optional

from pydantic import BaseModel, Field

from iris.common.pyris_message import PyrisMessage
from iris.domain.data.user_dto import UserDTO
from iris.domain.pipeline_execution_dto import PipelineExecutionSettingsDTO
from iris.domain.status.stage_dto import StageDTO


class ChatPipelineExecutionBaseDataDTO(BaseModel):
    chat_history: List[PyrisMessage] = Field(alias="chatHistory", default=[])
    user: Optional[UserDTO]
    settings: Optional[PipelineExecutionSettingsDTO]
    initial_stages: Optional[List[StageDTO]] = Field(
        default=None, alias="initialStages"
    )
