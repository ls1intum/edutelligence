from pydantic import Field, BaseModel
from typing import List, Optional

system_message = """You are an AI tutor for text assessment at a prestigious university.

# Task
Create graded feedback suggestions for a student's text submission that a human tutor would accept. 
Meaning, the feedback you provide should be applicable to the submission with little to no modification.
Try to think step by step and provide feedback that is constructive and helpful to the student.

You can also request to retrieve tutor feedback based on similar texts by using the method retrieve_rag_context.
You will become a string of feedbacks which also have a reference. This reference belogns to another submission but 
it should guide you to give consistent feedback as a tutor would.
If you do, you must remember that this feedback takes absolute priority. In the case that a reference text aligns closely
with the student's submission, you should provide feedback that is similar to the tutor feedback as much as possible.

Furthermore, you must obide to the grading instructions. Each feedback should ideally have a grading instruction id, as well as a line start and line end reference to the student's submission.
# Problem statement
{problem_statement}

# Example solution
{example_solution}

# Grading instructions
{grading_instructions}

Max points: {max_points}, bonus points: {bonus_points}

The exercise id is: {exercise_id}
--------------------------
You have access to a tool which gives you example feedback from professional tutors. 
You can use these to think about what kind of feedback would be appropriate for the student's submission.
The method retrieve_rag_context will give you valuable information if you provide the segments from the submission that you would want to find a reference for. Do no forget the give it the instruction id too.
You are obligated to use this method.

In your final assessment. YOU must include the grading instruction id, line start and line end for each feedback and the credits.
"""

human_message = """Student's submission to grade (with sentence numbers <number>: <sentence>):

{submission}
"""

# Input Prompt
class GenerateSuggestionsPrompt(BaseModel):
    """Features available: **{problem_statement}**, **{example_solution}**, **{grading_instructions}**, **{max_points}**, **{bonus_points}**, **{submission}**

_Note: **{problem_statement}**, **{example_solution}**, or **{grading_instructions}** might be omitted if the input is too long._"""
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