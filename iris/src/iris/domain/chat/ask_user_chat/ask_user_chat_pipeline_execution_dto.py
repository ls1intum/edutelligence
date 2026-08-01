from typing import Any, Optional

from pydantic import Field

from iris.domain.chat.chat_pipeline_execution_dto import (
    ChatPipelineExecutionDTO,
)
from iris.domain.event.pyris_event_dto import PyrisEventDTO


class AskUserPipelineExecutionDTO(ChatPipelineExecutionDTO):
    event_payload: Optional[PyrisEventDTO[Any]] = Field(None, alias="eventPayload")
    min_questions: int = Field(alias="minQuestions")
    max_questions: int = Field(alias="maxQuestions")
    questions_asked: int = Field(alias="questionsAsked")
