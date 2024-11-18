from typing import Optional, Dict
from pydantic import BaseModel

class ExerciseModel(BaseModel):
    submission_id: int
    exercise_id: int
    transformed_submission: str
    problem_statement: Optional[str] = None
    max_points: float
    bonus_points: float
    grading_instructions: Optional[str] = None
    submission_uml_type: str
    transformed_example_solution: Optional[str] = None
    element_id_mapping: Dict[str, str]
    id_type_mapping: Dict[str, str]