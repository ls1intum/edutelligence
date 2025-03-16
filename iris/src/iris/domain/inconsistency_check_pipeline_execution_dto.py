from pydantic import BaseModel

from .pipeline_execution_dto import PipelineExecutionDTO
from .data.programming_exercise_dto import ProgrammingExerciseDTO


class InconsistencyCheckPipelineExecutionDTO(BaseModel):
    execution: PipelineExecutionDTO
    exercise: ProgrammingExerciseDTO
