from pydantic import BaseModel, Field

from . import PipelineExecutionDTO


class RewritingPipelineExecutionDTO(BaseModel):
    execution: PipelineExecutionDTO
    course_id: int = Field(alias="courseId")
    to_be_rewritten: str = Field(alias="toBeRewritten")
