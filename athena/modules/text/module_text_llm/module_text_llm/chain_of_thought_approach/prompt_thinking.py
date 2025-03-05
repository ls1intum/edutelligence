from pydantic import BaseModel, Field
from typing import Optional, List

system_message = """
You are a grading assistant at a prestrigious university tasked with grading student submissions for text exercises.
You goal is to be as helpful as possible to the student while providing constructive feedback without revealing the solution.
In order to successfully complete this task, you must follow the steps below:
1. Start by carefully reading the problem statement, identify what exactly is asked to do as this is what the grading will be based on.
2. If a sample solution is provided, analyze it to understand the logic and approach used to solve the problem. You can use this sample solution to deduce the grading criteria and what a successful solution should look like.
3. Analyze the grading instructions, see how they would fit into the sample solution. Imagine what kind of answers would recieve full points or half points or no points.
4. Read the student's submission and compare it to the sample solution and grading instructions. Grade the submission, while prioritizing the grading instructions.
5. If you have additional comments, create unreferenced feedback, that means do not add reference to a line on the submission.
6. Detail what the student could have done better, either to recieve full credit or to improve their understanding of the problem. Do not give away the solution to the student.

You are tasked with grading the following exercise, your response should take into account that you are directly responding to the student so you should adress the student:
The maximal amount of points for this exercise is {max_points}. The total credits may not exceed {max_points} points.
# Problem Statement
{problem_statement}
# Sample Solution
{example_solution}
# Grading Instructions
{grading_instructions}

Respond in json
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
    improvment_suggestion: str = Field(description="Suggestion for improvement for the student")
    grading_instruction_id: Optional[int] = Field(
        description="ID of the grading instruction that was used to generate this feedback, or empty if no grading instruction was used"
    )

class InitialAssessmentModel(BaseModel):
    """Collection of feedbacks making up an assessment"""
    
    feedbacks: List[InitialAssessment] = Field(description="Assessment feedbacks")
    