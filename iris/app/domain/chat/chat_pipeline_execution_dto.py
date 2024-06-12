from typing import List, Optional

from pydantic import Field

from app.domain import PipelineExecutionDTO, PipelineExecutionSettingsDTO
from app.domain.pyris_message import PyrisMessage
from app.domain.data.user_dto import UserDTO
from app.domain.status.stage_dto import StageDTO


class ChatPipelineExecutionDTO(PipelineExecutionDTO):
    chat_history: List[PyrisMessage] = Field(alias="chatHistory", default=[])
    user: Optional[UserDTO]
    settings: Optional[PipelineExecutionSettingsDTO]
    initial_stages: Optional[List[StageDTO]] = Field(
        default=None, alias="initialStages"
    )
