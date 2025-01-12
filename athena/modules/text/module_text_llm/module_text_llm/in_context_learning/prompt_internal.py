from pydantic import Field, BaseModel
from typing import List, Optional

system_message = """\
You are an AI tutor for text assessment at a prestigious university.

# Task
You are an assistant at a prestigious University. You are assisting in assessing student text based submissions.
In order to do so, it is important to have structurred grading instructions, which will be continuesly updated.

Your task is to use the provided grading instructions and use the example solution, to provide examples for how 
the grading instruction is utilized.


"""

human_message = """\
# Problem statement
{problem_statement}

# Example solution
{example_solution}

# Grading instructions
{grading_instructions}
Max points: {max_points}, bonus points: {bonus_points}\
    
Respond in json.
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
class GradingInstruction(BaseModel):
    title: str = Field(description="Very short title, i.e. feedback category or similar", example="Logic Error")
    description: str = Field(description="Feedback description")
    # line_start: Optional[int] = Field(description="Referenced line number start, or empty if unreferenced")
    # line_end: Optional[int] = Field(description="Referenced line number end, or empty if unreferenced")
    credits: float = Field(0.0, description="Number of points received/deducted")
    grading_instruction_id: int = Field(
        description="ID of the grading instruction that was used to generate this feedback, or empty if no grading instruction was used"
    )
    examples: List[str] = Field(description="Examples of how the grading instruction is utilized")

class InternalGradingInstructions(BaseModel):
    """Collection of feedbacks making up an assessment"""
    
    grading_instructions: List[GradingInstruction] = Field(description="Assessment feedbacks")
    