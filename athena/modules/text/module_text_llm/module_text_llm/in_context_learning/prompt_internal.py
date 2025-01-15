from pydantic import Field, BaseModel
from typing import List, Dict, Optional

system_message = """\
You are an assistant at a prestigious University.
Another AI assistant will grade student text submission based on the grading instructions.

# Task
Your task is to generate a set of grading instructions that will help the AI assistant give feedback to students that is consistent with human feedback.


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

system_message_upgrade = """
You are tasked with upgrading the following Grading instructions. 
You have been given some tutor feedback based on a student submission to do so. 
Keep in mind that you must stay consistent with the original grading instructions.
Do not remove any grading instructions, only add new ones if absoluetly necessary in the case that you think the llm will provide feedback consistent to the tutor.
"""

human_message_upgrade = """\

# Internal Grading instructions
{internal_SGI}

You must include the Ai Feedback and tutor feedback into the feedback history depending on the criterion used.
This is a list, so you must include all the feedbacks that are relevant to the grading instruction id.

#(Your) AI Feedback
{ai_feedback}

### Tutor Feedback
Now you will recieve the tutor feedback. Take note of the structure:
suggestion:accepted means that the ai feedback was accepted by the tutor
suggestion:adapted means that the ai feedback was only adapted but not completely rejected
if neither of this is present it means that the tutor gave new feedback.
Take careful not of feedback that are present in the ai_feedback but not on the tutor feedback, this means that the tutor completely deleted your feedback and you shuould note this.
#Tutor Feedback
{tutor_feedback}

# Submission
{submission}

#
Max points: {max_points}, bonus points: {bonus_points}\
    
Respond in json.
"""

class GenerateSuggestionsPrompt(BaseModel):
    """\
Features available: **{problem_statement}**, **{example_solution}**, **{grading_instructions}**, **{max_points}**, **{bonus_points}**, **{submission}**

_Note: **{problem_statement}**, **{example_solution}**, or **{grading_instructions}** might be omitted if the input is too long._\
"""
    system_message: str = Field(default=system_message,
                                description="Message for priming AI behavior and instructing it what to do.")
    human_message: str = Field(default=human_message,
                               description="Message from a human. The input on which the AI is supposed to act.")
    
    
class FeedbackInstance(BaseModel):
    tutor_referenced_text: str = Field(None, description="Text from the submission that the tutor used to generate this feedback")
    tutor_credits: float = Field(0.0, description="Number of points received/deducted by the tutor")
    tutor_feedback: str = Field(None, description="Feedback provided by the tutor for this instance")
    
    ai_referenced_text: str = Field(description="Text from the submission that the AI used to generate this feedback")
    ai_credits: float = Field(0.0, description="Number of points received/deducted by the AI")
    ai_feedback: str = Field(description="YOUR AI Feedback")
    
    consistent: bool = Field(False, description="Whether the AI feedback is consistent with the tutor feedback")
    difference: str = Field(None, description="Difference between the AI and tutor feedback, describe how AI could do better")
    
class GradingInstruction(BaseModel):
    # title: str = Field(description="Very short title, i.e. feedback category or similar", example="Logic Error")
    description: str = Field(description="Feedback description")
    credits: float = Field(0.0, description="Number of points received/deducted")
    grading_instruction_id: int = Field(description="ID of the grading instruction that was used to generate this feedback, or empty if no grading instruction was used")

class Criterion(BaseModel):
    criterion_title: str = Field(description="Title of the criterion")
    grading_instructions: List[GradingInstruction] = Field(description="Feedbacks for the criterion")
    feedback_history: List[FeedbackInstance] = Field(default_factory=list, description="History of feedback instances related to this grading instruction")
    can_use_multiple_times : bool = Field(False, description="Whether the grading instruction can be used multiple times")
    
class InternalGradingInstructions(BaseModel):
    """Collection of feedbacks making up an assessment"""
    problem_statement: str = Field(description="The Problem statement")
    example_solution: str = Field(description="The Example Solution")
    grading_instructions: List[Criterion] = Field(description="Assessment feedbacks")
    