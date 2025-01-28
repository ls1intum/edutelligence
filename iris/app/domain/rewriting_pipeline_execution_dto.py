from pydantic import Field, BaseModel
from . import PipelineExecutionDTO


class RewritingPipelineExecutionDTO(BaseModel):
    execution: PipelineExecutionDTO
    to_be_rewritten: str = Field(alias="toBeRewritten")
