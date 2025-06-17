from pydantic import BaseModel, Field
from typing import Optional, List

system_message = """
You are an educational assistant tasked with analyzing the student's progress between two submissions for the same or similar exercise.

You are given:
- The student's current submission
- The student's most recent previous submission
- The feedback they received for their previous submission
- The grading instructions (including instruction IDs and their descriptions)

Follow the following guidelines step by step:
1: First compare the current and the previous submissions and identify the meaningful changes, that could affect students' grade from the exercise.
For every change find out if:
    - is_positive: True if student improve a part of the submission, false otherwise.
    - description: Describe what was changed or added
    - line_start: Referenced line number start on the current submission, or empty if unreferenced
    - line_end: Referenced line number end on the current submission, or empty if unreferenced
    - grading_instruction_id: ID of the grading instruction that this change references to, or empty if no grading instruction was used
2: Then compare these changes you found with the previously given feedback. Figure out if the feedback was potentially used in the current submission:
    - was_implemented: True if student made use of this feedback
    - feedback_id: ID of the feedback

Instructions:
- Return each change as a structured item.
- Do not include redundant or superficial wording changes unless they affect meaning.
- Focus on conceptual and structural changes that are important in terms of grading instructions or example solution, not on grammar.

Problem statement: 
{problem_statement}

Sample Solution:
{example_solution}

Previous submission: 
{latest_submission}

Feedback on previous submission: 
{latest_feedback}
"""

human_message = """\
Student\'s current submission (with sentence numbers <number>: <sentence>):
\"\"\"
{submission}
\"\"\"\
"""


# Input Prompt
class AnalyzingPrompt(BaseModel):
    """\
Features available: **{problem_statement}**, **{example_solution}**, **{grading_instructions}**, **{max_points}**, **{bonus_points}**, **{submission}**, **{learner_profile}**

_Note: **{problem_statement}**, **{example_solution}**, or **{grading_instructions}** might be omitted if the input is too long._\
"""
    system_message: str = Field(default=system_message,
                                description="Message for priming AI behavior and instructing it what to do.")
    human_message: str = Field(default=human_message,
                               description="Message from a human. The input on which the AI is supposed to act.")


# Output Object
class SubmissionChange(BaseModel):
    is_positive: bool = Field(description="True if student improve a part of the submission, false otherwise.")
    description: str = Field(description="Description of the change")
    line_start: Optional[int] = Field(description="Referenced line number start, or empty if unreferenced")
    line_end: Optional[int] = Field(description="Referenced line number end, or empty if unreferenced")
    grading_instruction_id: Optional[int] = Field(
        description="ID of the grading instruction that this change references to, or empty if no grading instruction was used"
    )


class FeedbackAnalysis(BaseModel):
    was_implemented: bool = Field(description="True if student made use of this feedback.")
    feedback_id: Optional[int] = Field(description="ID of the feedback")


class SubmissionComparisonResult(BaseModel):
    changes: List[SubmissionChange] = Field(description="List of changes between the previous and current submissions")
    feedback_analyses: list[FeedbackAnalysis] = Field(description="List of previous feedback analysis")
