from pydantic import BaseModel, Field
from typing import Optional, List

system_message = """ 
        You are an AI Tutor. 
        You are tasked with grading a student submission based on this problem statement and grading instructions. 
        You must not excede the maximum amount of points. 
        Take time to think, which points on the grading instructions are relevant for the students submission.
        Further more, if a feedback is specific to a sentence in the student submission, that specify this as well on your feedback. 
        Also specify, when possible, which grading instruction you are refering to.
        Referenced sentences must not overlap.
        # Problem statement
        {problem_statement}

        # Grading instructions
        {grading_instructions}
        Max points: {max_points}. The total points granted in all feedback elements must not exceed {max_points}.
        Format your response in the following way:
        Grading instruction <id> (sentence <x> to <y>): <feedback>, credits: <credits>
        If the feedback is unreferenced simple right Unreferenced
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
Features available: **{problem_statement}**, **{example_solution}**, **{grading_instructions}**, **{max_points}**, **{bonus_points}**, **{submission}**

_Note: **{problem_statement}**, **{example_solution}**, or **{grading_instructions}** might be omitted if the input is too long._\
"""
    system_message: str = Field(default=system_message,
                                description="Message for priming AI behavior and instructing it what to do.")
    human_message: str = Field(default=human_message,
                               description="Message from a human. The input on which the AI is supposed to act.")
  
# Output Object
class InitialAssessment(BaseModel):
    title: str = Field(description="Very short title, i.e. feedback category or similar", example="Logic Error")
    description: str = Field(description="Feedback description")
    line_start: Optional[int] = Field(description="Referenced line number start, or empty if unreferenced")
    line_end: Optional[int] = Field(description="Referenced line number end, or empty if unreferenced")
    credits: float = Field(0.0, description="Number of points received/deducted")
    reasoning: str = Field(description="Reasoning why the feedback was given")
    impprovment_suggestion: str = Field(description="Suggestion for improvement for the student")

class InitialAssessmentModel(BaseModel):
    """Collection of feedbacks making up an assessment"""
    
    feedbacks: List[InitialAssessment] = Field(description="Assessment feedbacks")