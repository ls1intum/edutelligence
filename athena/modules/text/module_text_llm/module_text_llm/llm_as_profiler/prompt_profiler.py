from typing import List, Optional
from enum import Enum
from pydantic import BaseModel, Field


system_message = """
You are an educational analyst evaluating a student's answer to a text-based exercise.

Your task is to:
1. Identify the student's demonstrated competencies (what they understand or do well).
2. Identify the student's challenges (misconceptions, errors, or difficulties).
3. Identify missing components in the student's response (important points that were not addressed).
4. Estimate the student's level of understanding using the response quality levels below.
5. Suggest the next level the student should aim for, based on the current response.

You will receive:
- The student's submission (with line numbers)
- The correct solution (if available)
- Grading instructions or rubric (if available)

Instructions:
- Be specific in describing competencies and challenges.
- Use line numbers when referencing issues in the submission.
- Include a response quality level only if it is reasonably clear.
- Suggest a next-level learning target only if it is helpful.
- If students miss some parts of the question, point that out without referencing their submission (no line_end, line_start)

Response Quality Levels:
- Off-Target: The response is irrelevant or not aligned with the question or course content.
- Insufficient Knowledge: The response attempts to address the question but lacks key concepts or terminology.
- Incomplete Answer: The student covers only part of the required answer or omits key elements.
- Partially Correct: The response includes relevant and partially accurate content, but lacks completeness or clarity.
- Correct: The response is accurate, complete, and well-structured.

Output Format:
Return only valid JSON. Do not include any explanation or comments outside the JSON.

<Exercise Details>

Problem Statement:
{problem_statement}

Example Solution:
{example_solution}

Grading Instructions:
{grading_instructions}
"""


human_message = """\
Student\'s submission to grade (with sentence numbers <number>: <sentence>):
\"\"\"
{submission}
\"\"\"\
"""


# Input Prompt
class ProfilerPrompt(BaseModel):
    """\
Features available: **{problem_statement}**, **{example_solution}**, **{grading_instructions}**, **{max_points}**, **{bonus_points}**, **{submission}**, **{practical_theoretical}**, **{creative_guidance}**, **{followup_summary}**, **{brief_detailed}**

_Note: **{problem_statement}**, **{example_solution}**, or **{grading_instructions}** might be omitted if the input is too long._\
"""
    system_message: str = Field(default=system_message,
                                description="Message for priming AI behavior and instructing it what to do.")
    human_message: str = Field(default=human_message,
                               description="Message from a human. The input on which the AI is supposed to act.")


# Output Object

class ResponseQualityLevel(str, Enum):
    OFF_TARGET = "Off-Target"  # The response is irrelevant or unrelated to the task
    INSUFFICIENT_KNOWLEDGE = "Insufficient Knowledge"  # Shows lack of understanding of key concepts
    INCOMPLETE_ANSWER = "Missing Points"  # Leaves out required parts of the answer
    PARTIALLY_CORRECT = "Partially Correct"  # Contains some correct information but is incomplete or poorly explained
    FULLY_CORRECT = "Correct"  # Accurate, complete, and well-structured answer


class ResponseAnalysisItem(BaseModel):
    description: str = Field(
        description="Detailed explanation of a specific issue or observation in the student's response, such as a misconception, omission, or vague explanation."
    )
    response_quality_level: ResponseQualityLevel = Field(
        description="Estimated level of the student's understanding based on the current response, using the custom response quality levels."
    )
    grading_instruction_id: Optional[int] = Field(
        default=None,
        description="Optional reference ID to the grading instruction or rubric item that this analysis relates to."
    )
    line_start: Optional[int] = Field(
        default=None,
        description="Line number in the student's submission where this issue begins, if applicable."
    )
    line_end: Optional[int] = Field(
        default=None,
        description="Line number in the student's submission where this issue ends, if applicable."
    )


class StudentResponseAnalysis(BaseModel):
    analyses: List[ResponseAnalysisItem] = Field(
        description="A list of issues, gaps, or errors identified in the student's response, each with a quality assessment and optional references."
    )

