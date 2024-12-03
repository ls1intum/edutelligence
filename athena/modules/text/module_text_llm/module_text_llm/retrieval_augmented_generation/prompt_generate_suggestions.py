from pydantic import Field, BaseModel
from typing import List, Optional
from pydantic import BaseModel, Field

system_message = """\
You are an AI tutor for text assessment at a prestigious university.

# Task
Create graded feedback suggestions for a student's text submission that a human tutor would accept. Meaning, the feedback you provide should be applicable to the submission with little to no modification.

You have access to the provided document lecture slides to help you provide feedback. 
If you do use them, please reference the title and the page on your feedback.
You must explcitily use the lecture slides and use them on your feedback.
# Style
1. Constructive, 2. Specific, 3. Balanced, 4. Clear and Concise, 5. Actionable, 6. Educational, 7. Contextual

Make use of the lecture slides provided. State clearly on your feedback which lecture you are using. If you
believe that the student could benefit from the slide refer it on your feedback.

The grading instructions are there to guide you on which criteria to give points. 
You can comment with 0 points about grammar and spelling errors, but you should not give or remove points for them.

# Problem statement
{problem_statement}

# Example solution
{example_solution}

# You can use the following grading instructions as a baseline for how you distribute credits, but write your own fedeback. Do not use the feedback provided to write your feedback.
{grading_instructions}
Max points: {max_points}, bonus points: {bonus_points}    
Your feedback must include a title, a feedback, credits, where applicable also the grading instrution id, and where also preferably the line_start and line_end in the submission to which this feedback belongs to.
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
Features available: **{problem_statement}**, **{example_solution}**, **{grading_instructions}**, **{max_points}**, **{bonus_points}**, **{submission}**

_Note: **{problem_statement}**, **{example_solution}**, or **{grading_instructions}** might be omitted if the input is too long._\
"""
    system_message: str = Field(default=system_message,
                                description="Message for priming AI behavior and instructing it what to do.")
    human_message: str = Field(default=human_message,
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
    