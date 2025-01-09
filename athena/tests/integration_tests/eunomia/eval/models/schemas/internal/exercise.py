import uuid
from typing import Dict, Optional
from pydantic import BaseModel, Field
from eval.models.schemas.external.structured_grading_instructions import StructuredGradingInstructions


class Exercise(BaseModel):
    id: int = Field(default_factory=lambda: abs(uuid.uuid4().int) % (2**31 - 1))
    title: str
    type: str
    max_points: float
    bonus_points: float
    grading_instructions: str
    problem_statement: str
    example_solution: Optional[str] = None
    grading_criteria: StructuredGradingInstructions
    meta: Dict = Field(default_factory=dict)