from pydantic import BaseModel, Field

from iris.common.pyris_message import PyrisMessage
from iris.domain import PipelineExecutionDTO
from iris.domain.data.text_exercise_dto import TextExerciseDTO


class TextExerciseChatPipelineExecutionDTO(BaseModel):
    execution: PipelineExecutionDTO
    exercise: TextExerciseDTO
    conversation: list[PyrisMessage] = Field(default=[])
    current_submission: str = Field(alias="currentSubmission", default="")
