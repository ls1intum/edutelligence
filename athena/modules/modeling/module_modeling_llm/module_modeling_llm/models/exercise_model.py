from typing import Optional
from pydantic import BaseModel

class ExerciseModel(BaseModel):
    submissionId: int
    exerciseId: int
    transformed_submission: str
    problem_statement: Optional[str] = None
    max_points: float
    bonus_points: float
    grading_instructions: Optional[str] = None
    submission_uml_type: str
    transformed_example_solution: Optional[str] = None
    element_id_mapping: dict[str, str]