from typing import List, Optional
from enum import Enum
from pydantic import BaseModel, Field


system_message = """
You are an educational analyst evaluating a student's response to a text-based exercise. 
Your goal is to compare the expected competencies for solving the exercise with what the student has demonstrated.

Your task is to:
1. Analyze the exercise based on the problem statement, sample solution, and grading instructions.
2. Extract the core competencies a student must demonstrate to fully answer the question. For each, specify the expected cognitive level (e.g., Recall, Understand, Apply, Analyze, Evaluate, Create) and relate it to grading instructions if available.
3. Compare each required competency to the student's submission:
   - Identify if the student demonstrated this competency.
   - Mark the competency as one of:
     - Correct: Accurately demonstrated with clear evidence.
     - Partially Correct: Some understanding shown, but incomplete or unclear.
     - Attempted Incorrectly: Tried to address the competency but misunderstood it.
     - Not Attempted: No trace of the required competency.
   - Provide textual evidence from the student's submission (quote or paraphrase) and line numbers if possible.

Guidelines:
- Be exhaustive: list all core competencies needed to solve the task, cover all the grading instructions and questions.
- Use only the student's submission, not your own interpretation, when evaluating evidence.
- Use clear and concise language.
- Do not repeat identical evidence for multiple competencies unless strictly necessary.
- If students miss some parts of the question, create not attempted competencies.

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
    description: str = Field(
        description="What the student needs to demonstrate (e.g., define a term, apply a method, justify a claim)."
    )
    cognitive_level: Optional[CognitiveLevel] = Field(
        default=None,
        description="Cognitive demand required by the question (Bloom level)."
    )
    grading_instruction_id: Optional[int] = Field(
        default=None,
        description="Reference to the corresponding grading instruction (if available)."
    )


class CompetencyEvaluation(BaseModel):
    competency: RequiredCompetency
    status: CompetencyStatus
    evidence: Optional[str] = Field(
        default=None,
        description="Quote or paraphrase from the student's submission that supports this evaluation."
    )
    line_start: Optional[int] = Field(
        default=None,
        description="Start line number in the student's submission where the competency is (partially) demonstrated."
    )
    line_end: Optional[int] = Field(
        default=None,
        description="End line number in the student's submission where the competency is (partially) demonstrated."
    )


class SubmissionCompetencyProfile(BaseModel):
    competencies: List[CompetencyEvaluation] = Field(
        description="List of all required competencies and how well the student fulfilled them."
    )
