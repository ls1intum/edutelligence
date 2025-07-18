from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum


# === ENUMS ===

class FeedbackType(str, Enum):
    FULL_POINTS = "Full Points"
    NEEDS_REVISION = "Needs Revision"
    NOT_ATTEMPTED = "Not Attempted"


# === FEEDBACK MODEL ===

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


# === PROMPT DEFINITIONS ===

system_message = """
You are a grading assistant. Your job is to generate high-quality, structured feedback based on the student's submission analysis.

You will receive:
- The problem statement
- A sample solution (for internal use only)
- Grading instructions with IDs and details
- The student's CURRENT submission (with line numbers)
- Student's feedback preferences
- A detailed analysis of the submission that includes:
    - Required competencies and how well the student demonstrated them
    - Evidence for the evaluation
    - A comparison to the PREVIOUS submission (if applicable), including whether a competency was added, removed, improved, or unchanged

Your task:
- For each core competency:
    - Create **feedback** that clearly explains the student's performance
    - Indicate whether they received full points, need revision, or didn't attempt it
    - Assign a specific next step (action) the student should take:
        - Example actions: “Review concept X”, “Improve explanation by doing Y”, “Explore topic Z further”
    - Reflect changes between previous and current submission:
        - If improved: Acknowledge progress
        - If regressed: Highlight what was lost
        - If unchanged and still weak: Gently prompt revision

For each feedback point:
- Include a title
- Add a clear description
- Specify feedback type: FULL_POINTS, NEEDS_REVISION, or NOT_ATTEMPTED
- Suggest an action
- Reference specific lines (line_start and line_end) if applicable
- Assign credits (float)
- Link to grading_instruction_id if relevant

Constraints:
- Do NOT reveal or hint at the correct solution
- Do NOT exceed {max_points} total points
- Avoid repeating the student's own words
- Focus on clarity, constructiveness, and progression awareness
- If part of the answer is missing or unchanged and still wrong, say so gently
- Reflect the student's learning journey - acknowledge effort and improvement when it exists

Inputs:
Problem Statement:
{problem_statement}

Sample Solution:
{example_solution}

Grading Instructions:
{grading_instructions}

Detailed Submission Analysis (contains comparison between previous and current submission):
{submission_analysis}

Student's feedback preferences:
{feedback_preferences}
"""

human_message = """\
Student\'s CURRENT submission to grade (with sentence numbers <number>: <sentence>):
\"\"\"
{submission}
\"\"\"\
"""

# === PROMPT WRAPPER CLASS ===

class GenerateSuggestionsPrompt(BaseModel):
    """Prompt class for generating feedback from merged competency and comparison analysis."""
    system_message: str = Field(default=system_message)
    human_message: str = Field(default=human_message)
