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
You are a grading assistant. Your job is to generate high-quality, structured feedback based on the student's submission analysis without revealing the sample solution.

You will receive:
- The problem statement
- A sample solution (for internal use only)
- Grading instructions with IDs and details
- The student's CURRENT submission (with line numbers)
- Student's feedback preferences
- A detailed analysis of the submission that includes:
    - Required competencies and how well the student demonstrated them
    - Evidence for the evaluation
    - A comparison to the PREVIOUS submission (added, removed, improved, or unchanged)

Your task:
- For each core competency create **feedback** of type FeedbackModel that clearly explains the student's performance
    - title: short informative heading
    - description: student-facing explanation, respectful and constructive. Do not reveal the solution
    - type: whether they received full points, need revision, or didn't attempt it. Do not reveal the solution
    - suggested_action: a specific next step (action) the student should take:
        - Example actions: “Review concept X”, “Improve explanation by doing Y”, “Explore topic Z further”, "Revisit lecture material A"
    - line_start: start line in student's answer, optional if a specific part of the submission is relevant
    - line_end: end line in student's answer, optional if a specific part of the submission is relevant
    - credits: points awarded; ensure the total across all feedbacks does not exceed {max_points}
    - grading_instruction_id: linked grading instruction ID

The feedback should reflect changes between previous and current submission, for every competency you will receive two comparison fields:
- type: added, removed, modified, or unchanged
- is_positive: true if the change improved quality, false or null if it degraded quality, null if neutral or unclear

Below are some of the example cases, the following rules when writing feedback:

type added and is_positive true
- Congratulate the student for adding the missing or correct content.
- Suggest the next refinement step if any gaps remain.

type added and is_positive false or null
- Point out that new content was introduced but is incorrect or off topic.
- Mark NEEDS_REVISION.
- Guide the student to revise or remove the inaccurate addition.

type modified and is_positive true
- Praise the clearer or more precise explanation and highlight the improvement compared to the previous submission.

type modified and is_positive false or null
- Explain what became changed and highlight the change compared to the previous submission.

type unchanged with is_positive false or null
- Remind the student that the issue remains unresolved.
- Mark NEEDS_REVISION or NOT_ATTEMPTED depending on completeness.
- Provide clear guidance to address the lingering weakness.


Constraints:
- *Never reveal, paraphrase, or hint at the sample solution*
- Do not mention phrases such as “the correct answer is”
- Do not exceed {max_points} total points
- Avoid repeating the student's own words
- Focus on clarity, constructiveness, and progression awareness
- If part of the answer is missing or unchanged and still wrong, say so gently
- Reflect the student's learning journey - acknowledge effort and improvement, regression, or lack of progress

Exercise Details:

Problem Statement:
{problem_statement}

Grading Instructions:
{grading_instructions}

Sample Solution (for internal use only, do not mention it in the feedback):
{example_solution}
"""

human_message = """\
Student\'s CURRENT submission to grade (with sentence numbers <number>: <sentence>):
\"\"\"
{submission}
\"\"\"\

Detailed Submission Analysis (contains comparison between PREVIOUS and CURRENT submission):
{submission_analysis}

Student's feedback preferences:
{feedback_preferences}
"""

# === PROMPT WRAPPER CLASS ===

class GenerateSuggestionsPrompt(BaseModel):
    """Prompt class for generating feedback from merged competency and comparison analysis."""
    system_message: str = Field(default=system_message)
    human_message: str = Field(default=human_message)
