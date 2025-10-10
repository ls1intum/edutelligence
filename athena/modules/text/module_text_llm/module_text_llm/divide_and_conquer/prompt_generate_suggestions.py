from pydantic import Field, BaseModel
from typing import List, Optional

from athena.schemas.grading_criterion import GradingCriterion

def get_human_message():
    return """
Now you must assess the following student submission and respond in json. The student submission to asses (with sentence numbers <number>: <sentence>):

\"\"\"
{submission}
\"\"\"\
"""

def double_curly_braces(input_str):
    return input_str.replace("{", " ").replace("}", " ")

def get_system_prompt(index,exericse,cirteria:GradingCriterion):
    system_prompt = """You are an AI Assistant TUTOR at a prestigious university tasked with assessing text submissions. You are tasked with assessing a submission from a student. The problem statement is:"""
    usage_count, formatted_criterion = format_divide_and_conquer_criteria(index,exericse,cirteria)
    return usage_count, system_prompt + formatted_criterion

def format_divide_and_conquer_criteria(index,exercise, criteria: GradingCriterion):
    criteria_explanation_prompt = ""
    problem_statement = f"""
    # Problem Statement 
    {double_curly_braces(exercise.problem_statement)}.
    # End Problem Statement
    A sample solution to the problem statement is:
    # Example Solution
    {double_curly_braces(exercise.example_solution)}
    # End Example Solution
    # General Instructions
    You do not have access to lecture materials, exercise sheet or other materials so do not make assumptions.
    # End General Instructions"""
    
    criteria_explanation_prompt += problem_statement
    # Handle Arbitrarily often criteria, this is denoted by use count 0.

    criteria_explanation_prompt += f""" 
    You have to assess the submission based on the criteria with the title: "{criteria.title}". There are
    {len(criteria.structured_grading_instructions)} structured assessment instructions options for this criteria.
    """
    usage_counts = [instruction.usage_count for instruction in criteria.structured_grading_instructions]
    use_same_usaged_count = False
    if (len(set(usage_counts)) == 1):
        use_same_usaged_count = True
    if use_same_usaged_count:
        criteria_explanation_prompt += f""" 
        {get_criteria_application(usage_counts)}.
        The structured assessment instructions are as follows: \n"""
    for idx,instruction in enumerate(criteria.structured_grading_instructions):
        criteria_explanation_prompt += f""" 
        Instruction Number {idx+1}: Apply {instruction.credits} credits if the following description fits the students submission: "{instruction.instruction_description}. A possible feedback could be in the likes of "{instruction.feedback}" but you may adjust it as you see fit, however stay focused only on this criteria on your feedback. Apply assessment instruction id {instruction.id} to this segment of the submission. \n
        """
    return usage_counts[0] ,criteria_explanation_prompt

def get_criteria_application(usage_counts):
    usaged_count_prompt = ""
    if usage_counts[0] == 0:
        usaged_count_prompt = "You may apply this criteria as many times as it is needed if it fits the submission."
    elif usage_counts[0] == 1:
        usaged_count_prompt = "You may only apply this criteria ONCE. You must pick the instruction that best fits the submission. "
    else:
        usaged_count_prompt = f"You may apply thic criteria {usage_counts[0]} times. Each time must pick the instruction that best fits the submission."
    
    usaged_count_prompt += """ For this criteria you have different levels of assessment to give, based on the structured assessment instructions."""
    usaged_count_prompt += """For different segments of the submission you may apply a different assessment instruction that is fitting to that segment and give it its respective deserved credits. 
    Identify all segments of the submission that relate to this criteria and its instructions and apply the correct feedback as described by the instructions. 
    Keep in mind that the student might seperate his answers throught the whole submission. 
    """ if usage_counts[0] != 1 else "You may apply this criteria only once and choose only a SINGLE assessment instruciton that best fits the submission!"
    return usaged_count_prompt

class FeedbackModel(BaseModel):
    """ A Feedback object consisting of the criteria title, the feedback text, a line_start and line_end to depict
    a reference to the text, creidts to depcit the credit amount given and an assessment_instruction_id to depict the assessment instruction ID used"""
    criteria: str = Field(description="Short Criteria title!")
    feedback: str = Field(description="The feedback in text form.")
    line_start: Optional[int] = Field(None, description="Referenced line number start, or empty if unreferenced")
    line_end: Optional[int] = Field(None, description="Referenced line number end, or empty if unreferenced")
    credits: float = Field(0.0, description="Number of credits received/deducted")
    assessment_instruction_id: Optional[int] = Field(
        None, description="ID of the assessment instruction that was used to generate this feedback, or empty if no assessment instruction was used"
    )

class AssessmentModel(BaseModel):
    """Collection of feedbacks making up an assessment"""
    assessment: List[FeedbackModel] = Field(description="Assessment feedbacks")
    