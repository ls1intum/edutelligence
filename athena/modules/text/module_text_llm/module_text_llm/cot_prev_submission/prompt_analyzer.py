from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum

system_message = """
You are an educational assistant tasked with analyzing the differences between two student submissions for the same exercise.

You are given:
- The current submission
- The previous submission
- Feedback previously given to the student
- Grading instructions with IDs and descriptions

Your goal is to identify grading-relevant differences and similarities between the two submissions.

Follow these steps:

Step 1: Identify grading-relevant changes

Detect all meaningful differences between the previous and current submissions. For each, specify:
- type: one of 'added', 'removed', or 'modified'
- is_positive:
    - true if the change improves the answer (for example, adds clarity, structure, or correctness)
    - false if the change is a regression (for example, removes or weakens a good explanation)
- description: Explain what changed and why it matters for grading
- line_start, line_end: Refer to the relevant lines in the current submission (if applicable)
- grading_instruction_id: Link to the related rubric item, if known

Notes:
- 'added' means new content appeared in the current version
- 'removed' means previously present content is now missing. If a concept or explanation was present in the previous submission but is now missing or weakened in the current one, this should be marked as 'removed' and is_positive should be false.
- 'modified' means content was rewritten or altered
- Focus on conceptual, structural, or factual changes — ignore superficial grammar or formatting
- This is the most important step — complete this before moving on

Step 2: Identify unchanged but relevant parts

After listing changes, detect unchanged content that is still relevant for grading. Only include unchanged elements if:
- They were mentioned in previous feedback
- They relate directly to grading instructions
- Their presence or absence may affect future feedback decisions

For these, specify:
- type: 'unchanged'
- is_positive: null
- description: Explain what was preserved and why it matters
- line_start, line_end: Refer to the current submission (if applicable)
- grading_instruction_id: Link to rubric if relevant

Be specific and consistent. Do not omit important changes. Avoid repetition.

Problem statement:
{problem_statement}

Sample solution:
{example_solution}

"""


human_message = """\
Student's previous submission (with sentence numbers <number>: <sentence>):
\"\"\"
{previous_submission}
\"\"\"

Student's current submission (with sentence numbers <number>: <sentence>):
\"\"\"
{submission}
\"\"\"
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
class ComparisonType(str, Enum):
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"


class SubmissionComparison(BaseModel):
    type: ComparisonType = Field(description="Type of comparison: added, removed, modified, or unchanged.")
    is_positive: Optional[bool] = Field(description="True if the comparison is an improvement, false if it is a regression, undefined if the same")
    description: str = Field(description="Description of the comparison and how it affects grading")
    line_start: Optional[int] = Field(description="Referenced line number in current submission (if applicable)")
    line_end: Optional[int] = Field(description="Referenced line number in current submission (if applicable)")
    grading_instruction_id: Optional[int] = Field(description="ID of the grading instruction referenced by this comparison, if any")


class SubmissionComparisonResult(BaseModel):
    comparison: List[SubmissionComparison] = Field(description="List of comparisons between the previous and current submissions")
