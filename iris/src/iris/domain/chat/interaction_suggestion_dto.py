from typing import List, Optional

from pydantic import BaseModel, Field

from iris.common.pyris_message import PyrisMessage


class InteractionSuggestionPipelineExecutionDTO(BaseModel):
    chat_history: List[PyrisMessage] = Field(alias="chatHistory", default=[])
    last_message: Optional[str] = Field(alias="lastMessage", default=None)
    problem_statement: Optional[str] = Field(
        alias="problemStatement", default=None
    )
