from pydantic import Field

from iris.domain import ChatPipelineExecutionDTO
from iris.domain.data.text_exercise_dto import TextExerciseDTO


class TextExerciseChatPipelineExecutionDTO(ChatPipelineExecutionDTO):
    exercise: TextExerciseDTO
    current_submission: str = Field(alias="currentSubmission", default="")
