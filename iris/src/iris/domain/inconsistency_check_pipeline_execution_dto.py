from pydantic import BaseModel

from .data.programming_exercise_dto import ProgrammingExerciseDTO
from .pipeline_execution_dto import PipelineExecutionDTO


class InconsistencyCheckPipelineExecutionDTO(BaseModel):
    execution: PipelineExecutionDTO
    exercise: ProgrammingExerciseDTO
