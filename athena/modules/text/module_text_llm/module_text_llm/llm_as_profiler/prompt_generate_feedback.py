from pydantic import BaseModel, Field
from typing import List, Optional

system_message = """
You are a grading assistant at a prestigious university tasked with assessing student submissions for exercises. Your goal is to be as helpful as possible while providing constructive feedback based on predefined grading criteria, without revealing the correct solution.

You will receive:
- A problem statement
- A sample solution
- Grading instructions
- A structured summary of the student's performance, including demonstrated competencies and learning challenges
- The maximum achievable score

Your task:
1. Carefully study the problem statement to understand what is expected from the student.
2. If a sample solution is provided, use it to understand the intended reasoning or structure.
3. Use the grading instructions to identify relevant assessment criteria.
4. Review the student's submission in light of the student_assessment, which includes:
- competencies: things the student did well
- challenges: areas that need improvement, with line references and suggestions
- current_level: current Bloom's Taxonomy level
- target_level: desired Bloom's level of learning

Additional Guidelines
- Total credit awarded must not exceed {max_points}.
- Feedback should be constructive, respectful, and clear.
- Do not copy-paste grading instructions, student's submission, or solutions.
- Do not include any metadata or extra commentary outside the expected JSON schema.

<Inputs>

Student's Performance:
{student_assessment}

Max Score:
{max_points}

Problem Statement:
{problem_statement}

Sample Solution:
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

class GenerateSuggestionsPrompt(BaseModel):
    """\
Features cit available: **{initial_feedback}**, **{max_points}**, **{student_grade}**, **{learner_profile}**

"""
    second_system_message: str = Field(default=system_message,
                                       description="Message for priming AI behavior and instructing it what to do.")
    answer_message: str = Field(default=human_message,
                                description="Message from a human. The input on which the AI is supposed to act.")

# Output Object

class FeedbackModel(BaseModel):
    title: str = Field(description="Very short title, i.e. feedback category or similar", example="Logic Error")
    description: str = Field(description="Student-friendly description, written to be read by the student directly.")
    line_start: Optional[int] = Field(description="Referenced starting line number from the student's submission, or empty if unreferenced")
    line_end: Optional[int] = Field(description="Referenced ending line number from the student's submission, or empty if unreferenced")
    credits: float = Field(0.0, description="Number of points received/deducted")
    grading_instruction_id: Optional[int] = Field(
        description="ID of the grading instruction that was used to generate this feedback, or empty if no grading instruction was used"
    )


class AssessmentModel(BaseModel):
    """Collection of feedbacks making up an assessment"""
    feedbacks: List[FeedbackModel] = Field(description="Assessment feedbacks")
