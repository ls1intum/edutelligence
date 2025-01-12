from pydantic import Field, BaseModel
from typing import List, Optional

system_message_upgrade = """
You are tasked with upgrading the following Grading instructions. 
You have been given some tutor feedback based on a student submission to do so. 
Keep in mind that you must stay consistent with the original grading instructions.
Do not remove any grading instructions, only add new ones if absoluetly necessary in the case that you think the llm will provide feedback consistent to the tutor.
"""

human_message_upgrade = """\
# Problem statement
{problem_statement}

# Example solution
{example_solution}

# Original Grading Instructions
{grading_instructions}

# Internal Grading instructions
{internal_SGI}

#Tutor Feedback
{feedbacks}

# Submission
{submission}

#
Max points: {max_points}, bonus points: {bonus_points}\
    
Respond in json.
"""

system_message = """\
You are an AI tutor for text assessment at a prestigious university.

# Task
You are an assistant at a prestigious University. You are assisting in assessing student text based submissions.
In order to do so, it is important to have internal structurred grading instructions that will help the llm give better feedback, which will be continuesly updated.

Your task is to use the provided grading instructions and use the example solution, to create a set of grading instructions that a machine can
better understand and use to give feedback to students that is consistent with human feedback.

Stay focused on the existing grading instructions, do not add new criteria, for example if grammar, clarity and whatever else is not an instruction do not add it.
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
    student_text_example: List[str] = Field(description="Examples student text that would receive this feedback")
    # maximum_usage_count: conint(gt=0) = Field(description="Maximum number of times the grading instruction can be used, positive number")
    
class InternalGradingInstructions(BaseModel):
    """Collection of feedbacks making up an assessment"""
    
    grading_instructions: List[GradingInstruction] = Field(description="Assessment feedbacks")
    