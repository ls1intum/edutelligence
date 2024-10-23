from typing import Optional, List

from pydantic import Field, BaseModel

from app.common.pyris_message import PyrisMessage


class InteractionSuggestionPipelineExecutionDTO(BaseModel):
    chat_history: List[PyrisMessage] = Field(alias="chatHistory", default=[])
    last_message: Optional[str] = Field(alias="lastMessage", default=None)
    problem_statement: Optional[str] = Field(alias="problemStatement", default=None)
