from pydantic import BaseModel, Field
from enum import Enum
from typing import List, Optional

system_message = """
You are a grading assistant at a university. Your task is to assess student submissions for text-based exercises and provide constructive, respectful, and helpful feedback without revealing the correct solution.

You will receive:
- A problem statement
- A sample solution (for internal reference only)
- Grading instructions
- The student's submission (with line numbers)
- The maximum score
- A structured analysis of the competencies required to solve the task, and how the student performed for each one

Instructions:
1. Read the problem statement to understand what the student was asked to do.
2. Use the sample solution only to understand the intended reasoning and structure.
3. Review the grading instructions to identify how responses are evaluated.
4. Review the structured competency analysis. Each item includes:
   - A competency the student was expected to demonstrate
   - The associated cognitive level (e.g., Understand, Apply, Analyze)
   - An evaluation of how well the student demonstrated it (Correct, Partially Correct, Attempted Incorrectly, Not Attempted)
   - Optional evidence with line numbers
5. Follow the below steps for generating the each point of feedback:
    - Write a short title summarizing the feedback
    - Include line_start and line_end if the feedback refers to a specific part of the answer
    - Include credits (points awarded or deducted)
    - Suggest the action student should take regarding the diagnosis (Review Concept, Improve Explanation, Extend Thinking)
        - Review Concept: When student faces conceptual misunderstandings; suggest them to revisit foundational material. Tell them "Go over this subject/topic" without explaining/revealing answer.
        - Improve Explanation: When student is partially correct; suggest to elaborate or clarify and try again to strengthen their answer. Tell them what they should do better, do not reveal the solution
        - Extend Thinking: When student is fully or mostly correct; deepen insight or explore related ideas. Provide a clear actionable follow-up question or things they can they take a look further.
    - Write a clear explanation directly addressed to the student according to the suggested action
    - Assign credits gained or lost for this competency, aligned with grading instruction (if available)
    - Include grading_instruction_id if related to a rubric item
    - Ensure feedback adds value beyond what the student already wrote - avoid simply agreeing or repeating. 

You may also provide general feedback that does not refer to any specific line. In that case, set line_start and line_end to null, and credits to 0.

Guidelines:
- Do not, no matter what, reveal the solution
- Do not exceed the maximum total score: {max_points}
- Do not copy text from the student's answer, rubric, or solution
- Do not repeat the student's sentences
- Do not include metadata or extra commentary
- Do not limit the feedback to structured competency analysis items
- Cover all the grading instructions and questions

<Inputs>

Structured Competency Analysis:
{competency_analysis}

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
    """A prompt model for generating structured feedback on student submissions.
    
    This class provides the system and human messages used to instruct an LLM to analyze
    student submissions and generate constructive feedback based on competency analysis,
    grading instructions, and problem requirements.
    """
    second_system_message: str = Field(default=system_message,
                                       description="Message for priming AI behavior and instructing it what to do.")
    answer_message: str = Field(default=human_message,
                                description="Message from a human. The input on which the AI is supposed to act.")

# Output Object

class SuggestedAction(str, Enum):
    REVIEW_CONCEPT = "Review Concept"     # For conceptual misunderstandings; revisit foundational material
    IMPROVE_EXPLANATION = "Improve Explanation"  # Partially correct; elaborate or clarify to strengthen understanding
    EXTEND_THINKING = "Extend Thinking"   # Fully or mostly correct; deepen insight or explore related ideas


class FeedbackModel(BaseModel):
    title: str = Field(
        description="A very short label summarizing the issue or focus of the feedback (e.g., 'Missing Concept', 'Strong Start')."
    )
    description: str = Field(
        description="Student-facing feedback message that explains the issue or suggestion in a constructive and clear way."
    )
    suggested_action: SuggestedAction = Field(
        description="Suggested action for the student as a next step."
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
