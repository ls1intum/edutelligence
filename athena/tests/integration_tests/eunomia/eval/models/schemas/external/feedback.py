from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict

class Feedback(BaseModel):
    model_config = ConfigDict(populate_by_name=True)  # Allow aliases
    
    id: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    credits: float = 0.0
    structured_grading_instruction_id: Optional[int] = Field(None, alias="structuredGradingInstructionId")
    is_graded: Optional[bool] = Field(None, alias="isGraded")
    meta: dict = Field(default_factory=dict)
    exercise_id: int = Field(..., alias="exerciseId")
    submission_id: int = Field(..., alias="submissionId")


class ModelingFeedback(Feedback):
    element_ids: Optional[List[str]] = Field(default_factory=list, alias="elementIds")
    reference: Optional[str] = None