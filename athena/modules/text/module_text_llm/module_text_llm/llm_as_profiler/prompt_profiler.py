from typing import List, Optional
from enum import Enum
from pydantic import BaseModel, Field


system_message = """
You are an educational analyst tasked with evaluating a student's answer to a text-based exercise.

Your goal is to:
1. Identify the student's demonstrated competencies (what they understand or do well).
2. Identify the student's challenges (mistakes, misconceptions, or difficulties).
3. Identify what student's missing (missing parts of of the solution).
4. Estimate the current cognitive level the student demonstrates using SOLO Taxonomy.
5. Suggest the next cognitive level the student should aim for (target level).

You will be given:
- The student's submission
- The correct solution or expected answer
- Grading instructions or rubric (if available)

Instructions:
- Be specific in describing competencies and challenges.
- Include SOLO level tags only if reasonably clear.
- Provide suggestions only when helpful.
- Include line references to the student's submission if possible.

SOLO Level Definitions:
- Limited Response: The student addresses one idea or misses the point.
- Partial Understanding: The student provides multiple relevant ideas, but treats them separately.
- Connected Understanding: The student connects ideas into a coherent structure, or reasons beyond the task.

Output Format:
Return only valid JSON, including line references where applicable. Do not add any comments or explanations outside the JSON block.

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

class SoloLevel(str, Enum):
    LIMITED = "Limited Response"
    PARTIAL = "Partial Understanding"
    CONNECTED = "Connected Understanding"


class Competency(BaseModel):
    description: str = Field(
        description="A description of what the student demonstrated successfully."
    )
    solo_level: Optional[SoloLevel] = Field(
        default=None,
        description="The SOLO Taxonomy level corresponding to this competency."
    )
    grading_instruction_id: Optional[int] = Field(
        description="ID of the grading instruction that was used to generate this feedback, or empty if no grading instruction was used"
    )
    line_start: Optional[int] = Field(description="Referenced starting line number from the student's submission, or empty if unreferenced")
    line_end: Optional[int] = Field(description="Referenced ending line number from the student's submission, or empty if unreferenced")


class Challenge(BaseModel):
    description: str = Field(
        description="A description of a missing part, learning challenge, misconception, or error identified in the student's response."
    )
    solo_level: Optional[SoloLevel] = Field(
        default=None,
        description="The SOLO's level that this challenge relates to."
    )
    suggestion: Optional[str] = Field(
        default=None,
        description="An optional suggestion or tip to help the student overcome this challenge."
    )
    grading_instruction_id: Optional[int] = Field(
        description="ID of the grading instruction that was used to generate this feedback, or empty if no grading instruction was used"
    )
    line_start: Optional[int] = Field(description="Referenced starting line number from the student's submission, or empty if unreferenced")
    line_end: Optional[int] = Field(description="Referenced ending line number from the student's submission, or empty if unreferenced")


class ProfileModel(BaseModel):
    competencies: List[Competency] = Field(
        description="A list of competencies the student has demonstrated in their submission."
    )
    challenges: List[Challenge] = Field(
        description="A list of learning challenges or misconceptions detected in the student's response."
    )
    current_level: Optional[SoloLevel] = Field(
        default=None,
        description="The highest SOLO level the student demonstrated in this exercise."
    )
    target_level: Optional[SoloLevel] = Field(
        default=None,
        description="The next SOLO level the student should aim to reach."
    )
