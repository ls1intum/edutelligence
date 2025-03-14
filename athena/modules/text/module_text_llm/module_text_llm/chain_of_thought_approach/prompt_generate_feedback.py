from pydantic import BaseModel, Field
from typing import List, Optional

system_message = """
         You gave the following feedback on the first iteration: {answer}
         On this step you need to refine your feedback. You will recieve the student submission once more.
         Make sure to follow the following steps to assess and improve your feedback:
         - Credits given or deducted should be consistent and tracable to the grading instructions and the sample solution, if it doesn't, consider improvements.
         - If you have your own additional improvements that are not present in the grading instructions, add them in a new feedback with 0 credits and no reference.
         - Remember that your response is directly seen by students and it should adress them directly.
         - For each feedback where the student has room for improvement, think about how the student could improve his solution.
         - Once you have thought how the student can improve the solution, formulate it in a way that guides the student towards the correct solution without revealing it directly.
         - References should not overlap, that means that no two feedback must have overlaping line_start and line_end.
         - If the feedback is general and not related to a specific line, leave line_start and line_end empty.
         - Consider improvements to the feedback if any of this points is not satisfied.
         You will be provided once again with the student submission.
         Respond in json

         """

human_message = """\
Student\'s submission to grade (with sentence numbers <number>: <sentence>):
\"\"\"
{submission}
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
    
    feedbacks: List[FeedbackModel] = Field(description="Assessment feedbacks")
    