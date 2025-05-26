from pydantic import BaseModel, Field
from enum import Enum
from typing import List, Optional

system_message = """
You are a grading assistant at a university. Your task is to assess student submissions for text-based exercises and provide constructive, respectful, and helpful feedback without revealing the correct solution.

You will receive:
- A problem statement
- A sample solution (for internal reference only)
- Grading instructions
- A structured analysis of the student's response
- The maximum score
- The student's feedback preferences

Instructions:
1. Read the problem statement to understand what the student was asked to do.
2. Use the sample solution only to understand the intended reasoning and structure.
3. Review the grading instructions to identify how responses are evaluated.
4. Read the structured analysis. Each item includes:
   - A description of what the student did well or struggled with
   - A response quality level (Off-Target, Missing Points, Partially Correct, Correct)
   - A grading instruction ID (optional)
   - Line references from the student submission (optional)

For each point of feedback:
- Write a short title summarizing the issue
- Write a clear explanation directly addressed to the student
- Choose one feedback type:
    - REVISIT_LECTURE: Review the material to understand the concept
    - ELABORATION: Your answer is mostly right but needs more explanation
    - HINT: You are partly right; here is a nudge to improve
    - VERIFICATION: Your answer is correct; please reflect or review further
- Include line_start and line_end if the feedback refers to a specific part of the answer
- Include credits (points awarded or deducted)
- Include grading_instruction_id if related to a rubric item

You may also provide general feedback that does not refer to any specific line. In that case, set line_start and line_end to null, and credits to 0.

Guidelines:
- Do not exceed the maximum total score: {max_points}
- Do not copy text from the student's answer, rubric, or solution
- Do not repeat the student's sentences
- Do not include metadata or extra commentary

<Inputs>

Student Response Analysis:
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

class FeedbackType(str, Enum):
    REVISIT_LECTURE = "Revisit Lecture"  # The student lacks conceptual understanding and should revisit the related material
    ELABORATION = "Elaboration"          # The student’s idea is on the right track but needs further explanation, depth, or precision
    HINT = "Hint"                        # The student made a partially correct attempt; give a nudge or suggestion without revealing the answer
    VERIFICATION = "Verification"        # The student gave a correct or mostly correct answer; invite them to double-check or reflect to reinforce learning


class FeedbackModel(BaseModel):
    title: str = Field(
        description="A very short label summarizing the issue or focus of the feedback (e.g., 'Missing Concept', 'Strong Start')."
    )
    description: str = Field(
        description="Student-facing feedback message that explains the issue or suggestion in a constructive and clear way."
    )
    type: FeedbackType = Field(
        description="The purpose or instructional intent of the feedback, used to adapt tone and guidance (i.e., verification, elaboration, hint, revisit lecture)."
    )
    line_start: Optional[int] = Field(
        description="Referenced starting line number from the student's submission, or empty if unreferenced"
    )
    line_end: Optional[int] = Field(
        description="Referenced ending line number from the student's submission, or empty if unreferenced"
    )
    credits: float = Field(
        default=0.0,
        description="The number of points awarded or deducted for this feedback item."
    )
    grading_instruction_id: Optional[int] = Field(
        description="The ID of the grading instruction or rubric item related to this feedback, if applicable."
    )


class AssessmentModel(BaseModel):
    """Collection of feedbacks making up an assessment"""
    feedbacks: List[FeedbackModel] = Field(description="Assessment feedbacks")
