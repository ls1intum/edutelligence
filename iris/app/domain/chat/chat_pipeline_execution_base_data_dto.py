from typing import List, Optional

from pydantic import Field, BaseModel

from app.domain import PipelineExecutionSettingsDTO
from app.common.pyris_message import PyrisMessage
from app.domain.data.user_dto import UserDTO
from app.domain.status.stage_dto import StageDTO


class ChatPipelineExecutionBaseDataDTO(BaseModel):
    chat_history: List[PyrisMessage] = Field(alias="chatHistory", default=[])
    user: Optional[UserDTO]
    settings: Optional[PipelineExecutionSettingsDTO]
    initial_stages: Optional[List[StageDTO]] = Field(
        default=None, alias="initialStages"
    )
