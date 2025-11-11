from typing import List, Optional, Literal
from enum import Enum

from athena.schemas import Competency
from pydantic import BaseModel, Field


class CompetencyStatus(str, Enum):
    NOT_ATTEMPTED = "Not Attempted"
    ATTEMPTED_INCORRECTLY = "Attempted Incorrectly"
    PARTIALLY_CORRECT = "Partially Correct"
    CORRECT = "Correct"


class CompetencyChange(BaseModel):
    type: Literal["added", "removed", "modified", "unchanged"]
    is_positive: Optional[bool] = Field(None, description="Whether the change is positive (improvement)")
    description: str = Field(..., description="Explanation of the change and its grading relevance")
    line_start: Optional[int] = Field(None, description="Start line number in current submission")
    line_end: Optional[int] = Field(None, description="End line number in current submission")
    grading_instruction_id: Optional[int] = Field(None, description="Relevant grading instruction ID")


class EnhancedCompetencyEvaluation(BaseModel):
    competency: Competency = Field(..., description="The competency that was evaluated")
    status: CompetencyStatus = Field(..., description="The student's status for the competency")
    evidence: Optional[str] = Field(None, description="Quote or paraphrase from student's current submission")
    line_start: Optional[int] = Field(None, description="Start line number for evidence")
    line_end: Optional[int] = Field(None, description="End line number for evidence")
    changes: Optional[List[CompetencyChange]] = Field(None, description="Relevant changes between submissions")


class SubmissionAnalysis(BaseModel):
    competencies: List[EnhancedCompetencyEvaluation] 