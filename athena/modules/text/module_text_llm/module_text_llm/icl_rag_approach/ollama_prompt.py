from pydantic import Field, BaseModel
from typing import List, Optional

class Segment(BaseModel):
    segment: str = Field(description="Segment of the text")
    title: str = Field(description="Title of the criterion that this text adresses")
    
class Segmentation(BaseModel):
    segments: List[Segment] = Field(description="List of segments")
    
system_message_segment = """
You are an AI asisstnat for text assessment at a prestigious university.
You are tasked with segmenting the following text into parts that address different parts of the problem statement.
You can use the criteria from provided grading instructions to help in regards to the semantic segmentation of the text.
# Problem Statement
{problem_statement}

# Grading Instructions
{grading_instructions}

Return a valid json response, which contains a list. 
Each element of the list should be a Segment which contains the segment text and the criterion title which it adresses.
Keep in mind that not all criterion might be adressed in the text.
"""

human_message_segment = """
# Submission
# {submission}
"""
system_message = """You are an AI tutor for text assessment at a prestigious university.

# Task
Create graded feedback suggestions for a student's text submission that a human tutor would accept. Meaning, the feedback you provide should be applicable to the submission with little to no modification.

# Problem statement
{problem_statement}

# Example solution
{example_solution}

# Grading instructions
{grading_instructions}
Max points: {max_points}, bonus points: {bonus_points}
The exercise id is: {exercise_id}
--------------------------

You have access to the following tutor feedback on similar texts:
{rag_context}
Respond in json.
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