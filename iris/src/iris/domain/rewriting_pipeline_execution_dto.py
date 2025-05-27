from enum import Enum

from pydantic import BaseModel, Field

from . import PipelineExecutionDTO


class RewritingPipelineExecutionDTO(BaseModel):
    execution: PipelineExecutionDTO
    course_id: int = Field(alias="courseId")
    to_be_rewritten: str = Field(alias="toBeRewritten")
    variant: "RewritingVariant" = Field(alias="variant", default="FAQ")


class RewritingVariant(str, Enum):
    FAQ = "FAQ"
    PROBLEM_STATEMENT = "PROBLEM_STATEMENT"