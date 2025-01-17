from pydantic import BaseModel, Field
from typing import List, Optional

system_message = """
Your task is to format the given text from the human into a json that will be the assessment presented to a student. 
The json must strictly follow the following instructions:
1. You should only reply in valid json without any additional comments.
2. The json must begin with the property "feedback_list" which is an array of many feedback elements. 
3. Each element of this array only has these fields and it must contain all of them with the exact same name as given here: "feedback_list", which contains "title", "description", "credits", "line_start", "line_end", "title", "grading_instruction_id".
4. The maximum amount of credits to be given is {max_points} credits.

"""

human_message = """\
\"\"\"
{answer}
\"\"\"\
"""

# Input Prompt

class CoTGenerateSuggestionsPrompt(BaseModel):
    """\
Features cit available: **{problem_statement}**, **{example_solution}**, **{grading_instructions}**, **{max_points}**, **{bonus_points}**, **{submission}**

_Note: **{problem_statement}**, **{example_solution}**, or **{grading_instructions}** might be omitted if the input is too long._\
"""
    second_system_message: str = Field(default=system_message,
                                description="Message for priming AI behavior and instructing it what to do.")
    answer_message: str = Field(default=human_message,
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
    
    feedback_list: List[FeedbackModel] = Field(description="Assessment feedbacks")