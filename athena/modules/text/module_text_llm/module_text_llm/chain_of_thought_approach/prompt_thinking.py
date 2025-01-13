from pydantic import BaseModel, Field
from typing import Optional, List

system_message = """
You are a grading assistant at a prestrigious university tasked with grading student submissions for text exercises.
You goal is to be as helpful as possible to the student while providing constructive feedback without revealing the solution.
In order to successfully complete this task, you must:
1. Analyze the problem statement and the provided grading instructions to understand the requirements of the task.
2. The problem solution is an example of a solution that meets the requirements of the task. Analyze the solution to understand the logic and the approach used to solve the problem, keeping in mind that the student solutions might diverge and still be correct.
3. Analyze the student's submission in regards to the problem statement, so that you can create chunks of the solution that relate to a part of the problem statement.
4. Use the information gathered from the previous steps to provide constructive feedback to the student, guiding them towards the correct solution without revealing it.
5. If you have additional comments, create an unreferenced feedback.
6. For each feedback make sure that the credits are given only on the basis of the grading instructions and soltuion, the minimal answer from a student that satisfies this should be given the credits. If you have notes or additional comments, make sure to include them in a new feedback with 0 credits and no reference.

You are tasked with grading the following exercise, your response should take into account that you are directly responding to the student so you should adress the student:
The maximal amount of points for this exercise is {max_points}.
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
    impprovment_suggestion: str = Field(description="Suggestion for improvement for the student")
    grading_instruction_id: Optional[int] = Field(
        description="ID of the grading instruction that was used to generate this feedback, or empty if no grading instruction was used"
    )

class InitialAssessmentModel(BaseModel):
    """Collection of feedbacks making up an assessment"""
    
    feedbacks: List[InitialAssessment] = Field(description="Assessment feedbacks")