from pydantic import Field, BaseModel

from app.common.pyris_message import PyrisMessage

from . import PipelineExecutionDTO


class ChatGPTWrapperPipelineExecutionDTO(BaseModel):
    execution: PipelineExecutionDTO
    conversation: list[PyrisMessage] = Field(default=[]) 