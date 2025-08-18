from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from enum import Enum


class CompetencyStatus(str, Enum):
    NOT_ATTEMPTED = "Not Attempted"
    ATTEMPTED_INCORRECTLY = "Attempted Incorrectly"
    PARTIALLY_CORRECT = "Partially Correct"
    CORRECT = "Correct"


class CognitiveLevel(str, Enum):
    RECALL = "Recall"
    UNDERSTAND = "Understand"
    APPLY = "Apply"
    ANALYZE = "Analyze"
    EVALUATE = "Evaluate"
    CREATE = "Create"


class RequiredCompetency(BaseModel):
    description: str = Field(..., description="The skill or knowledge the student is expected to demonstrate.")
    cognitive_level: Optional[CognitiveLevel] = Field(None, description="Bloom's Taxonomy level")
    grading_instruction_id: Optional[int] = Field(None, description="Reference to grading instruction if applicable")


class CompetencyChange(BaseModel):
    type: Literal["added", "removed", "modified", "unchanged"]
    is_positive: Optional[bool] = Field(None, description="Whether the change is positive (improvement)")
    description: str = Field(..., description="Explanation of the change and its grading relevance")
    line_start: Optional[int] = Field(None, description="Start line number in current submission")
    line_end: Optional[int] = Field(None, description="End line number in current submission")
    grading_instruction_id: Optional[int] = Field(None, description="Relevant grading instruction ID")


class EnhancedCompetencyEvaluation(BaseModel):
    competency: RequiredCompetency
    status: CompetencyStatus
    evidence: Optional[str] = Field(None, description="Quote or paraphrase from student's current submission")
    line_start: Optional[int] = Field(None, description="Start line number for evidence")
    line_end: Optional[int] = Field(None, description="End line number for evidence")
    changes: Optional[List[CompetencyChange]] = Field(None, description="Relevant changes between submissions")


class SubmissionAnalysis(BaseModel):
    competencies: List[EnhancedCompetencyEvaluation] 