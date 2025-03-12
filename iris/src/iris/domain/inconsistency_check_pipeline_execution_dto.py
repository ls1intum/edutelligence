from pydantic import BaseModel

from . import PipelineExecutionDTO
from .data.programming_exercise_dto import ProgrammingExerciseDTO


class InconsistencyCheckPipelineExecutionDTO(BaseModel):
    execution: PipelineExecutionDTO
    exercise: ProgrammingExerciseDTO
