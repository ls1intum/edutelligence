from pydantic import Field, model_validator

from iris.domain.chat.chat_pipeline_execution_dto import (
    ChatPipelineExecutionDTO,
)


class AskUserPipelineExecutionDTO(ChatPipelineExecutionDTO):
    min_questions: int = Field(alias="minQuestions")
    max_questions: int = Field(alias="maxQuestions")
    questions_asked: int = Field(alias="questionsAsked")

    @model_validator(mode="after")
    def validate_question_bounds(self):
        """Ensure min_questions does not exceed max_questions."""
        if self.min_questions > self.max_questions:
            raise ValueError("min_questions must not be greater than max_questions")
        return self
