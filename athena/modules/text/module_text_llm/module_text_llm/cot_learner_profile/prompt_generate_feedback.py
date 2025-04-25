from pydantic import BaseModel, Field
from typing import List, Optional

system_message = """
You gave the following feedback on the first iteration: {answer}

Now, refine your feedback by reviewing the student submission once more. In this step:

1. Ensure credits and deductions are consistent with the grading instructions and sample solution.
2. If additional feedback (not covered by grading instructions) is helpful, include it with 0 credits and no line reference.
3. Each feedback entry must have unique line references; do not overlap line_start and line_end.
4. General comments should omit line references.
5. Feedback must be addressed directly to the student.
6. Provide actionable suggestions for improvement without revealing the exact solution.
7. If you include a follow-up question:
   - Make it clear, specific, and actionable.
   - Avoid vague or overly broad prompts.
   - Ask only one question per feedback entry.
   - Optionally provide a short example before the question to ground it in reality.
8. Tailor the feedback style to match the students preferences:
{learner_profile}

Your goal is to help the student reflect and improve. Encourage critical thinking while staying aligned with their learning style.

Respond in JSON.
"""

human_message = """\
Student\'s submission to grade (with sentence numbers <number>: <sentence>):
\"\"\"
{submission}
\"\"\"\
"""


# Input Prompt

class GenerateSuggestionsPrompt(BaseModel):
    """\
Features cit available: **{answer}**, **{submission}**, **{learner_profile}**

"""
    second_system_message: str = Field(default=system_message,
                                       description="Message for priming AI behavior and instructing it what to do.")
    answer_message: str = Field(default=human_message,
                                description="Message from a human. The input on which the AI is supposed to act.")

# Output Object

class FeedbackModel(BaseModel):
    title: str = Field(description="Very short title, i.e. feedback category or similar", example="Logic Error")
    description: str = Field(description="Feedback description")
    line_start: Optional[int] = Field(description="Referenced line number start, or empty if unreferenced")
    line_end: Optional[int] = Field(description="Referenced line number end, or empty if unreferenced")
    credits: float = Field(0.0, description="Number of points received/deducted")
    grading_instruction_id: Optional[int] = Field(
        description="ID of the grading instruction that was used to generate this feedback, or empty if no grading instruction was used"
    )


class AssessmentModel(BaseModel):
    """Collection of feedbacks making up an assessment"""

    feedbacks: List[FeedbackModel] = Field(description="Assessment feedbacks")
