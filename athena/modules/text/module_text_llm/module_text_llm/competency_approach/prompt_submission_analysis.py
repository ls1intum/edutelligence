from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from enum import Enum


# === ENUMS ===

class CompetencyStatus(str, Enum):
    NOT_ATTEMPTED = "Not Attempted"
    ATTEMPTED_INCORRECTLY = "Attempted Incorrectly"
    PARTIALLY_CORRECT = "Partially Correct"
    CORRECT = "Correct"

# === MODELS ===

class CompetencyChange(BaseModel):
    type: Literal["added", "removed", "modified", "unchanged"]
    is_positive: Optional[bool] = Field(None, description="Whether the change is positive (improvement)")
    description: str = Field(..., description="Explanation of the change and its grading relevance")
    line_start: Optional[int] = Field(None, description="Start line number in current submission")
    line_end: Optional[int] = Field(None, description="End line number in current submission")
    grading_instruction_id: Optional[int] = Field(None, description="Relevant grading instruction ID")
    competency_id: Optional[int] = Field(None, description="Relevant competency ID")


class CompetencyEvaluation(BaseModel):
    status: CompetencyStatus
    evidence: Optional[str] = Field(None, description="Quote or paraphrase from student's current submission")
    line_start: Optional[int] = Field(None, description="Start line number for evidence")
    line_end: Optional[int] = Field(None, description="End line number for evidence")
    changes: Optional[List[CompetencyChange]] = Field(None, description="Relevant changes between submissions")


class SubmissionAnalysis(BaseModel):
    competencies: List[CompetencyEvaluation]


# === PROMPTS ===

system_message = """
You are an educational evaluator reviewing a student's progress on a text-based exercise.

You will:"

1. Evaluate the student's CURRENT SUBMISSION:
    - For each required competency, assess how well the student demonstrates it using:
        - CORRECT
        - PARTIALLY CORRECT
        - ATTEMPTED INCORRECTLY
        - NOT ATTEMPTED
    - Provide short evidence from the current submission (quote/paraphrase) and line numbers if possible.

2. Compare the PREVIOUS SUBMISSION to the CURRENT SUBMISSION:
    - Identify if the competency was improved, added, weakened, or removed.
    - For each change, specify:
        - Type: added / removed / modified / unchanged
        - Is_positive: true (improvement), false (regression), or null
        - A short description of the change and its grading relevance
        - Related grading_instruction_id if applicable
        - Line numbers in current submission if possible

Only output structured data in JSON format.
Do NOT include superficial grammar or formatting differences.
Focus only on changes that affect grading or student understanding.

Problem Statement:
{problem_statement}

Sample Solution:
{example_solution}

Grading Instructions:
{grading_instructions}

Required Competencies:
{competencies}
"""

human_message = """
Student's PREVIOUS submission (with line numbers):
\"\"\"
{previous_submission}
\"\"\"

Student's CURRENT submission (with line numbers):
\"\"\"
{submission}
\"\"\"
"""


# === INPUT WRAPPER ===

class AnalysisPrompt(BaseModel):
    """Input wrapper for the submission analysis."""
    system_message: str = Field(default=system_message, description="System-level instructions")
    human_message: str = Field(default=human_message, description="Student submission comparison input template")

