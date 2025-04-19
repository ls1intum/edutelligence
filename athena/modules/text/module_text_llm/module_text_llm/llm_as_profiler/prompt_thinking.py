from typing import List, Optional
from enum import Enum
from pydantic import BaseModel, Field


system_message = """
You are an educational analyst tasked with evaluating a student's answer to a text-based exercise.

Your goal is to:
1. Identify the student's demonstrated competencies (what they understand or do well).
2. Identify the student's challenges (mistakes, misconceptions, or difficulties).
3. Estimate the current cognitive level the student demonstrates using Bloom's Taxonomy.
4. Suggest the next cognitive level the student should aim for (target level).
5. Include the student's known feedback style preference (brief/detailed, practical/theoretical).

You will be given:
- The student's submission
- The correct solution or expected answer
- Grading instructions or rubric (if available)
- The student's feedback style preference

Problem Statement:
{example_solution}

Example Solution:
{example_solution}

Grading Instructions:
{grading_instructions}

Student Feedback Style Preference:
{learner_profile}

Instructions:
- Be specific in describing competencies and challenges.
- Include Bloom level tags only if reasonably clear.
- Provide suggestions only when helpful.
- Return only valid JSON. Do not add any comments or explanations outside the JSON block.

"""


human_message = """\
Student\'s submission to grade (with sentence numbers <number>: <sentence>):
\"\"\"
{submission}
\"\"\"\
"""


# Input Prompt
class ThinkingPrompt(BaseModel):
    """\
Features available: **{problem_statement}**, **{example_solution}**, **{grading_instructions}**, **{max_points}**, **{bonus_points}**, **{submission}**, **{practical_theoretical}**, **{creative_guidance}**, **{followup_summary}**, **{brief_detailed}**

_Note: **{problem_statement}**, **{example_solution}**, or **{grading_instructions}** might be omitted if the input is too long._\
"""
    system_message: str = Field(default=system_message,
                                description="Message for priming AI behavior and instructing it what to do.")
    human_message: str = Field(default=human_message,
                               description="Message from a human. The input on which the AI is supposed to act.")


# Output Object

class BloomLevel(str, Enum):
    REMEMBER = "Remember"
    UNDERSTAND = "Understand"
    APPLY = "Apply"
    ANALYZE = "Analyze"
    EVALUATE = "Evaluate"
    CREATE = "Create"


class Competency(BaseModel):
    description: str = Field(
        description="A description of what the student demonstrated successfully."
    )
    bloom_level: Optional[BloomLevel] = Field(
        default=None,
        description="The Bloom's Taxonomy level corresponding to this competency."
    )


class Challenge(BaseModel):
    description: str = Field(
        description="A description of a learning challenge, misconception, or error identified in the student's response."
    )
    bloom_level: Optional[BloomLevel] = Field(
        default=None,
        description="The Bloom's level that this challenge relates to."
    )
    suggestion: Optional[str] = Field(
        default=None,
        description="An optional suggestion or tip to help the student overcome this challenge."
    )


class InitialAssessmentModel(BaseModel):
    competencies: List[Competency] = Field(
        description="A list of competencies the student has demonstrated in their submission."
    )
    challenges: List[Challenge] = Field(
        description="A list of learning challenges or misconceptions detected in the student's response."
    )
    current_level: Optional[BloomLevel] = Field(
        default=None,
        description="The highest Bloom's level the student demonstrated in this exercise."
    )
    target_level: Optional[BloomLevel] = Field(
        default=None,
        description="The next Bloom's level the student should aim to reach."
    )
