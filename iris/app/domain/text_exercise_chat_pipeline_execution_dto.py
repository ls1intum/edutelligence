from pydantic import BaseModel, Field

from app.domain import PipelineExecutionDTO, PyrisMessage
from app.domain.data.text_exercise_dto import TextExerciseDTO


class TextExerciseChatPipelineExecutionDTO(BaseModel):
    execution: PipelineExecutionDTO
    exercise: TextExerciseDTO
    conversation: list[PyrisMessage] = Field(default=[])
    current_submission: str = Field(alias="currentSubmission", default="")
