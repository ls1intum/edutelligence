from pydantic import BaseModel


class StructuredGradingInstructionsInputs(BaseModel):
    problem_statement: str
    max_points: float
    bonus_points: float
    grading_instructions: str
    submission_uml_type: str
    example_solution: str
    structured_instructions_output_format: str


structured_grading_instructions_system_message = """You are an AI tutor for {submission_uml_type} modeling exercise assessment at a prestigious university.

Create a structured grading instruction based on the given grading instructions (important), the solution diagram (if present) and the problem statement. The structured grading instruction should be highly detailed to ensure consistent grading across different tutors.

<Output Format>
{structured_instructions_output_format}
"""

structured_grading_instructions_human_message = """
<Exercise Problem Statement>
{problem_statement}

<Grading Instructions>
Max points: {max_points}, bonus points: {bonus_points}

Instructions:
{grading_instructions}

<Official Example Solution>
{example_solution}

Please return the structured grading instructions in the correct output json format.
"""
