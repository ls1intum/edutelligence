from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum


class FeedbackType(str, Enum):
    FULL_POINTS = "Full Points"
    NEEDS_REVISION = "Needs Revision"
    NOT_ATTEMPTED = "Not Attempted"


class FeedbackModel(BaseModel):
    title: str = Field(description="Short summary of the feedback issue or praise")
    description: str = Field(description="Student-facing explanation, respectful and constructive")
    type: FeedbackType = Field(description="Evaluation of the student's performance")
    suggested_action: str = Field(description="What the student should do next to improve or explore more")
    line_start: Optional[int] = Field(default=None, description="Start line in student's answer")
    line_end: Optional[int] = Field(default=None, description="End line in student's answer")
    credits: float = Field(default=0.0, description="Points awarded or deducted")
    grading_instruction_id: Optional[int] = Field(default=None, description="Linked grading instruction ID")


class AssessmentModel(BaseModel):
    feedbacks: List[FeedbackModel] 