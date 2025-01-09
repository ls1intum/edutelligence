from typing import Any, Dict, List
from pydantic import BaseModel


class Instruction(BaseModel):
    id: int
    credits: float
    grading_scale: str
    instruction_description: str
    feedback: str
    usage_count: int
    meta: Dict[str, Any] = {}

class Criterion(BaseModel):
    id: int
    title: str
    structured_grading_instructions: List[Instruction]
    meta: Dict[str, Any] = {}

StructuredGradingInstructions = List[Criterion]