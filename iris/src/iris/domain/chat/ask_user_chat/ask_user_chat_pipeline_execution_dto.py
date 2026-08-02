from pydantic import Field

from iris.domain.chat.chat_pipeline_execution_dto import (
    ChatPipelineExecutionDTO,
)


class AskUserPipelineExecutionDTO(ChatPipelineExecutionDTO):
    min_questions: int = Field(alias="minQuestions")
    max_questions: int = Field(alias="maxQuestions")
    questions_asked: int = Field(alias="questionsAsked")
